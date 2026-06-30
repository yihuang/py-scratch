"""
Runtime — the Scratch VM execution engine.

Manages threads, processes the scheduler loop, and dispatches opcode handlers.
"""

from __future__ import annotations

import heapq
import time
import math
import copy
import types
from collections.abc import Callable, Generator
from typing import Any
from .target import Target
from .thread import (
    YIELD,
    Thread,
    ThreadStatus,
    is_wait,
)
from .types import Block, Input

# Type alias: an opcode handler is a generator that yields control signals
# and (for reporters) ends by returning a value.
Handler = Callable[['Runtime', Target, Block], Generator[Any] | None]


# ── Runtime Clock ────────────────────────────────────────────────────────


class Clock:
    """Virtual 60 fps clock. Each ``step()`` call advances by one tick."""

    FPS = 60

    def __init__(self) -> None:
        self._tick: int = 0

    def now(self) -> float:
        """Virtual time in seconds since start."""
        return self._tick / self.FPS

    def tick(self) -> None:
        """Advance one frame."""
        self._tick += 1

    def frames_for(self, seconds: float) -> int:
        """Number of ticks needed to cover ``seconds``."""
        return max(1, math.ceil(seconds * self.FPS))

    def reset(self) -> None:
        self._tick = 0


# ── Runtime ──────────────────────────────────────────────────────────────


class Runtime:
    """The central runtime: holds targets, runs threads, dispatches opcodes."""

    def __init__(self) -> None:
        self.targets: list[Target] = []
        self.threads: list[Thread] = []
        self._handlers: dict[str, Handler] = {}
        self.clock = Clock()
        self.stage: Target | None = None
        self._keyboard: dict[str, bool] = {}
        self._wait_queue: list[tuple[float, int, Thread]] = []
        self._wait_seq = 0
        self._hat_index: dict[str, list[tuple[Target, str]]] = {}
        self.current_thread: Thread | None = None
        self._answer: str | None = None
        self._for_each_counter: float = 0
        self._real_time: bool = True
        self._time = time
        self._clones: list[Target] = []

    # ── Registration ──────────────────────────────────────────────────

    def register(self, opcode: str) -> Callable[[Handler], Handler]:
        """Decorator to register an opcode handler.

        The handler should be a generator function that accepts
        ``(runtime, target, block)``.
        """

        def deco(fn: Handler) -> Handler:
            self._handlers[opcode] = fn
            return fn

        return deco

    def register_all(self, mapping: dict[str, Handler]) -> None:
        """Register a dict of ``{opcode: handler_fn}``."""
        self._handlers.update(mapping)

    def get_handler(self, opcode: str) -> Handler | None:
        return self._handlers.get(opcode)

    # ── Target management ─────────────────────────────────────────────
    def add_target(self, target: Target) -> None:
        self.targets.append(target)
        if target.is_stage:
            self.stage = target
        self._index_target_hats(target)

    def _index_target_hats(self, target: Target) -> None:
        for bid, block in target.blocks.items():
            if block.top_level and block.opcode.startswith('event_'):
                self._hat_index.setdefault(block.opcode, []).append((target, bid))

    def sprite_targets(self) -> list[Target]:
        return [t for t in self.targets if not t.is_stage]

    def get_target_by_name(self, name: str) -> Target | None:
        for t in self.targets:
            if t.name == name:
                return t
        return None

    def clone_target(self, target_name: str) -> Target | None:
        """Create a clone of the named sprite."""
        src = self.get_target_by_name(target_name)
        if src is None or src.is_stage:
            return None
        clone = copy.deepcopy(src)
        clone._is_clone = True
        clone.name = f'{src.name}_clone'
        self._clones.append(clone)
        self.targets.append(clone)
        self._index_target_hats(clone)
        # Start all hat scripts on the clone
        for opcode in ['event_whenflagclicked', 'event_whenthisspriteclicked']:
            self.start_hat_for_opcode(opcode, target=clone)
        return clone

    def remove_clone(self, clone: Target) -> None:
        """Remove a clone from the runtime."""
        if clone._is_clone and clone in self._clones:
            self._clones.remove(clone)
            self.targets.remove(clone)
            for th in list(self.threads):
                if th.target is clone:
                    th.status = 'done'

    # ── Input evaluation ──────────────────────────────────────────────

    def evaluate(self, target: Target, block_id: str) -> Any:
        """Evaluate a reporter/boolean block by id and return its value.

        This runs synchronously; reporter chains are resolved atomically
        within one frame.  That matches Scratch's behaviour because
        reporters never wait.
        """
        block = target.blocks.get(block_id)
        if block is None:
            return None
        handler = self.get_handler(block.opcode)
        if handler is None:
            return None
        gen = handler(self, target, block)
        if gen is not None:
            try:
                while True:
                    val = next(gen)
                    # Reporters only yield REPORT(value); we collect it.
                    if isinstance(val, _Report):
                        return val.value
                    # Ignore YIELD/WAIT — should not happen in reporters,
                    # but handle gracefully.
            except StopIteration:
                pass
        return None

    def resolve_input(self, target: Target, inp: Input | Any) -> Any:
        """Resolve a block input to a concrete value.

        Accepts an ``Input`` object or any plain value.
        """
        if isinstance(inp, Input):
            value = inp.value
        else:
            value = inp

        if isinstance(value, str) and value in target.blocks:
            return self.evaluate(target, value)
        # Shadow pair: [block_id, literal] — use the literal.
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and isinstance(value[1], (int, float, str, bool))
        ):
            return value[1]
        return value

    def resolve_bool(self, target: Target, inp: Input | Any) -> bool:
        """Resolve a boolean-typed input."""
        v = self.resolve_input(target, inp)
        if isinstance(v, str):
            return v.lower() not in ('', 'false', '0')
        return bool(v)

    def resolve_num(self, target: Target, inp: Input | Any) -> float:
        """Resolve a numeric input."""
        return float(self.resolve_input(target, inp) or 0)

    # ── Thread lifecycle ──────────────────────────────────────────────

    def start_hat(self, opcode: str) -> list[Thread]:
        """Start threads for all hat blocks with the given opcode."""
        created: list[Thread] = []
        for target, bid in self._hat_index.get(opcode, []):
            block = target.blocks.get(bid)
            nxt = block.next if block else None
            thread = Thread(target=target, top_block=nxt or bid)
            thread.start()
            self.threads.append(thread)
            created.append(thread)
        return created

    def start_hat_for_opcode(self, opcode: str, target: Target | None = None) -> None:
        """Start hats for an opcode, optionally on a single target."""
        if target is not None:
            entries = [(target, bid) for (t, bid) in self._hat_index.get(opcode, []) if t == target]
        else:
            entries = self._hat_index.get(opcode, [])

        for t, bid in entries:
            block = t.blocks[bid]
            nxt = block.next if block else None
            thread = Thread(target=t, top_block=nxt or bid)
            thread.start()
            self.threads.append(thread)

    def start_key_hat(self, key_name: str) -> None:
        for target, bid in self._hat_index.get('event_whenkeypressed', []):
            block = target.blocks.get(bid)
            if block is None:
                continue
            fld = block.fields.get('KEY_OPTION')
            val = str(getattr(fld, 'value', fld or ''))
            if val.lower() != key_name.lower():
                continue
            nxt = block.next
            thread = Thread(target=target, top_block=nxt or bid)
            thread.start()
            self.threads.append(thread)

    # ── Scheduler ─────────────────────────────────────────────────────

    def step(self) -> None:
        if self._real_time:
            now = self._time.monotonic()
            while self._wait_queue and self._wait_queue[0][0] <= now:
                _, _, thread = heapq.heappop(self._wait_queue)
                if thread.status == ThreadStatus.WAITING:
                    thread.status = ThreadStatus.RUNNING
        else:
            tick = self.clock._tick
            while self._wait_queue and self._wait_queue[0][0] <= tick:
                _, _, thread = heapq.heappop(self._wait_queue)
                if thread.status == ThreadStatus.WAITING:
                    thread.status = ThreadStatus.RUNNING

        for thread in list(self.threads):
            if thread.is_done():
                continue
            if thread.status == ThreadStatus.WAITING:
                continue
            self._step_thread(thread)

        self.clock.tick()
        self.threads[:] = [t for t in self.threads if not t.is_done()]

    def _schedule_wake(self, thread: Thread, delay: float) -> None:
        thread.status = ThreadStatus.WAITING
        if self._real_time and delay > 0:
            wake_at = self._time.monotonic() + delay
        else:
            wake_at = self.clock._tick + self.clock.frames_for(delay)
        seq = self._wait_seq
        self._wait_seq += 1
        heapq.heappush(self._wait_queue, (wake_at, seq, thread))

    def _step_thread(self, thread: Thread) -> None:
        """Advance one thread by one 'instruction'."""
        self.current_thread = thread
        frame = thread.peek_frame()
        if frame is None:
            thread.status = ThreadStatus.DONE
            self.current_thread = None
            return
        block = thread.target.blocks.get(frame.block_id)
        if block is None:
            thread.pop_frame()
            self.current_thread = None
            return
        handler = self.get_handler(block.opcode)
        if handler is None:
            self._advance_to_next(thread)
            self.current_thread = None
            return
        if frame.gen is None:
            gen_or_val = handler(self, thread.target, block)
            if gen_or_val is None or not hasattr(gen_or_val, '__next__'):
                self._advance_to_next(thread)
                self.current_thread = None
                return
            if not isinstance(gen_or_val, types.GeneratorType):
                self._advance_to_next(thread)
                self.current_thread = None
                return
            frame.gen = gen_or_val
        try:
            yielded = next(frame.gen)
        except StopIteration:
            self._advance_to_next(thread)
            self.current_thread = None
            return
        if isinstance(yielded, _Report):
            result = yielded.value
            thread.pop_frame()
            parent = thread.peek_frame()
            if parent is not None:
                parent.saved['_result'] = result
            self.current_thread = None
            return
        wait_secs = is_wait(yielded)
        if wait_secs is not None and wait_secs > 0:
            self._schedule_wake(thread, wait_secs)
            self.current_thread = None
            return
        if yielded is YIELD:
            self.current_thread = None
            return
        self._advance_to_next(thread)
        self.current_thread = None

    def _advance_to_next(self, thread: Thread) -> None:
        """Move the thread's current frame to the next block in the chain.

        If the frame's block has a ``next``, push a new frame for it.
        Otherwise pop the frame — the thread may be done.
        """
        frame = thread.peek_frame()
        if frame is None:
            thread.status = ThreadStatus.DONE
            return

        block = thread.target.blocks.get(frame.block_id)
        if block and block.next:
            # Replace current frame with next block
            frame.block_id = block.next
            frame.gen = None
        else:
            thread.pop_frame()
            if not thread.stack:
                thread.status = ThreadStatus.DONE
            # If there's a parent frame, we're returning control to it

    def green_flag(self) -> None:
        for t in self.threads:
            t.status = ThreadStatus.DONE
        self.threads.clear()
        self._wait_queue.clear()
        self.start_hat('event_whenflagclicked')

    def broadcast(self, message: str) -> list[Thread]:
        started: list[Thread] = []
        for target, bid in self._hat_index.get('event_whenbroadcastreceived', []):
            block = target.blocks.get(bid)
            if block is None:
                continue
            fld = block.fields.get('BROADCAST_OPTION')
            val = str(getattr(fld, 'value', fld or ''))
            if val != message:
                continue
            nxt = block.next
            thread = Thread(target=target, top_block=nxt or bid)
            thread.start()
            self.threads.append(thread)
            started.append(thread)
        return started

    # ── Sub-stack execution helper ────────────────────────────────────

    def execute_substack(self, target: Target, block_id: str | None) -> Generator[Any]:
        """Generator: step through a linked list of blocks.

        Control blocks (repeat, if, etc.) should ``yield from`` this
        to execute their substack input.
        """
        bid = block_id
        while bid:
            block = target.blocks.get(bid)
            if block is None:
                break
            handler = self.get_handler(block.opcode)
            if handler is None:
                bid = block.next
                continue
            gen = handler(self, target, block)
            if gen is None or not hasattr(gen, '__next__'):
                # Instant block (no yield) — done immediately
                bid = block.next
                if bid:
                    yield YIELD
                continue
            try:
                while True:
                    val = next(gen)
                    yield val
            except StopIteration:
                pass
            bid = block.next
            if bid:
                yield YIELD


# ── Reporter-yield wrapper ─────────────────────────────────────────────


class _Report:
    """Wrapper around a reporter return value, yielded from generators."""

    __slots__ = ('value',)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f'Report({self.value!r})'


def report(value: Any) -> _Report:
    """Yield this from a reporter handler to return a value."""
    return _Report(value)
