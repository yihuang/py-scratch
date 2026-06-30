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
    Report,
    Thread,
    ThreadStatus,
    Wait,
    YIELD,
    YieldPass,
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
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0
        self._mouse_down: bool = False

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
        block = target.blocks[block_id]
        handler = self.get_handler(block.opcode)
        assert handler is not None
        gen = handler(self, target, block)
        if gen is not None:
            try:
                while True:
                    val = next(gen)
                    # Reporters only yield REPORT(value); we collect it.
                    if isinstance(val, Report):
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

        # Scratch variable/list reference: [type_code, name_or_id]
        if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], int):
            type_code, ref = value
            if type_code == 5:  # Variable reference
                var = target.lookup_variable(ref) or (
                    self.stage and self.stage.lookup_variable(ref)
                )
                return var.value if var else 0
            if type_code == 12:  # List reference
                lst = target.lookup_list(ref) or (
                    self.stage and self.stage.lookup_list(ref)
                )
                return lst.contents if lst else []
            # Other reference types (4=broadcast, etc.) — return the name
            return ref

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

    def num(self, target: Target, block: Block, name: str) -> float:
        """Resolve a named numeric input from *block*."""
        return self.resolve_num(target, block.inputs.get(name))

    def num_int(self, target: Target, block: Block, name: str) -> int:
        """Resolve a named numeric input and round to nearest int."""
        return round(self.num(target, block, name))

    def bool(self, target: Target, block: Block, name: str) -> bool:
        """Resolve a named boolean input from *block*."""
        return self.resolve_bool(target, block.inputs.get(name))

    def val(self, target: Target, block: Block, name: str) -> Any:
        """Resolve a named arbitrary input from *block*."""
        return self.resolve_input(target, block.inputs.get(name))

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

    def start_click_hat(self, scratch_x: float, scratch_y: float) -> None:
        """Start click hats for the sprite (or stage) at *(scratch_x, scratch_y)*."""
        # Hit-test sprites in reverse layer order (topmost first)
        sprites = sorted(self.sprite_targets(), key=lambda t: t.layer_order, reverse=True)
        for tgt in sprites:
            if not tgt.visible:
                continue
            # Simple radius check: bounding circle based on costume size
            radius = 30.0  # default placeholder radius
            if tgt.costume and tgt.costume.surface:
                w, h = tgt.costume.surface.get_size()
                radius = (math.sqrt(w * w + h * h) / 2) * (tgt.size / 100.0)
            dx = scratch_x - tgt.x
            dy = scratch_y - tgt.y
            if dx * dx + dy * dy <= radius * radius:
                for _, bid in self._hat_index.get('event_whenthisspriteclicked', []):
                    if bid in tgt.blocks:
                        nxt = tgt.blocks[bid].next
                        thread = Thread(target=tgt, top_block=nxt or bid)
                        thread.start()
                        self.threads.append(thread)
                return
        # No sprite hit — stage click
        stage = self.stage
        if stage is not None:
            for _, bid in self._hat_index.get('event_whenstageclicked', []):
                if bid in stage.blocks:
                    nxt = stage.blocks[bid].next
                    thread = Thread(target=stage, top_block=nxt or bid)
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
        match yielded:
            case Report(value=result):
                thread.pop_frame()
                parent = thread.peek_frame()
                if parent is not None:
                    parent.saved['_result'] = result
                self.current_thread = None
                return
            case Wait(seconds=secs):
                self._schedule_wake(thread, secs)
                self.current_thread = None
                return
            case YieldPass():
                self.current_thread = None
                return
            case _:
                raise RuntimeError(
                    f"Unknown yield {yielded!r} from {block.opcode!r} "
                    f"(block {block.id!r})"
                )

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


