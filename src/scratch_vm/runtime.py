"""
Runtime — the Scratch VM execution engine.

Manages threads, processes the scheduler loop, and dispatches opcode handlers.
"""

from __future__ import annotations

import time
import types

from typing import Any, Callable, Generator
from .target import Target
from .thread import (
    DONE,
    YIELD,
    Frame,
    Thread,
    ThreadStatus,
    is_wait,
    wait_yield,
)
from .types import Block, Input


# Type alias: an opcode handler is a generator that yields control signals
# and (for reporters) ends by returning a value.
Handler = Generator[Any, None, None]


# ── Runtime Clock ────────────────────────────────────────────────────────

class Clock:
    """Wall-clock abstraction, tickable for deterministic testing."""

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._pause_frames = 0  # for determinism, not used yet

    def now(self) -> float:
        return time.perf_counter() - self._start

    def reset(self) -> None:
        self._start = time.perf_counter()


# ── Runtime ──────────────────────────────────────────────────────────────

class Runtime:
    """The central runtime: holds targets, runs threads, dispatches opcodes."""

    def __init__(self) -> None:
        self.targets: list[Target] = []
        self.threads: list[Thread] = []
        self._handlers: dict[str, Callable[..., Handler]] = {}
        self.clock = Clock()
        # The stage target (first target, is_stage=True)
        self.stage: Target | None = None

    # ── Registration ──────────────────────────────────────────────────

    def register(self, opcode: str) -> Callable:
        """Decorator to register an opcode handler.

        The handler should be a generator function that accepts
        ``(runtime, target, block)``.
        """
        def deco(fn: Callable[..., Handler]) -> Callable:
            self._handlers[opcode] = fn
            return fn
        return deco

    def register_all(self, mapping: dict[str, Callable]) -> None:
        """Register a dict of ``{opcode: handler_fn}``."""
        self._handlers.update(mapping)

    def get_handler(self, opcode: str) -> Callable | None:
        return self._handlers.get(opcode)

    # ── Target management ─────────────────────────────────────────────

    def add_target(self, target: Target) -> None:
        self.targets.append(target)
        if target.is_stage:
            self.stage = target

    def sprite_targets(self) -> list[Target]:
        return [t for t in self.targets if not t.is_stage]

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
        if (isinstance(value, (list, tuple))
                and len(value) == 2
                and isinstance(value[1], (int, float, str, bool))):
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

    def start_hat(self, opcode: str, **opt_args: Any) -> list[Thread]:
        """Start threads for all hat blocks with the given opcode.

        Returns the list of created threads.
        """
        created: list[Thread] = []
        for target in self.targets:
            hat_ids = target.get_hat_blocks(opcode)
            for bid in hat_ids:
                thread = Thread(target=target, top_block=bid)
                # The hat block itself is a trigger — start from its *next*.
                hat_block = target.blocks.get(bid)
                if hat_block and hat_block.next:
                    thread.top_block = hat_block.next
                thread.start()
                self.threads.append(thread)
                created.append(thread)
        return created

    def start_hat_for_opcode(
        self, opcode: str, target: Target | None = None
    ) -> list[Thread]:
        """Start hats only on a specific target (or all if ``None``)."""
        targets = [target] if target else self.targets
        created: list[Thread] = []
        for t in targets:
            for bid in t.get_hat_blocks(opcode):
                thread = Thread(target=t, top_block=bid)
                hat_block = t.blocks.get(bid)
                if hat_block and hat_block.next:
                    thread.top_block = hat_block.next
                thread.start()
                self.threads.append(thread)
                created.append(thread)
        return created

    # ── Scheduler ─────────────────────────────────────────────────────

    def step(self) -> None:
        """Run exactly one step for each runnable thread."""
        now = self.clock.now()

        for thread in list(self.threads):
            if thread.is_done():
                continue

            # Check if a waiting thread should wake up
            if thread.status == ThreadStatus.WAITING:
                if thread.waiting_until is not None and now >= thread.waiting_until:
                    thread.status = ThreadStatus.RUNNING
                    thread.waiting_until = None
                else:
                    continue

            if not thread.is_runnable():
                continue

            self._step_thread(thread, now)

        # Sweep dead threads
        self.threads[:] = [t for t in self.threads if not t.is_done()]

    def _step_thread(self, thread: Thread, now: float) -> None:
        """Advance one thread by one 'instruction'."""
        frame = thread.peek_frame()
        if frame is None:
            thread.status = ThreadStatus.DONE
            return

        block = thread.target.blocks.get(frame.block_id)
        if block is None:
            thread.pop_frame()
            return

        # If no generator yet, create one
        handler = self.get_handler(block.opcode)
        if handler is None:
            # Unknown opcode — skip: pop frame, advance to next block
            self._advance_to_next(thread)
            return
        if frame.gen is None:
            gen_or_val = handler(self, thread.target, block)
            if gen_or_val is None or not hasattr(gen_or_val, '__next__'):
                # Instant block (no yield) — advance to next
                self._advance_to_next(thread)
                return
            if not isinstance(gen_or_val, types.GeneratorType):
                # Block that returned a non-None non-generator value
                # (shouldn't happen, but be safe)
                self._advance_to_next(thread)
                return
            frame.gen = gen_or_val

        # Step the generator
        try:
            yielded = next(frame.gen)
        except StopIteration:
            # Block finished normally
            self._advance_to_next(thread)
            return

        if isinstance(yielded, _Report):
            # Reporter result — deliver to parent frame
            result = yielded.value
            thread.pop_frame()
            parent = thread.peek_frame()
            if parent is not None:
                parent.saved['_result'] = result
            return

        wait_secs = is_wait(yielded)
        if wait_secs is not None and wait_secs > 0:
            thread.status = ThreadStatus.WAITING
            thread.waiting_until = now + wait_secs
            return

        if yielded is YIELD:
            thread.status = ThreadStatus.YIELD
            return

        # Unknown yield — skip
        self._advance_to_next(thread)

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
        """Broadcast the green-flag event."""
        self.start_hat('event_whenflagclicked')

    def broadcast(self, message: str) -> None:
        """Broadcast a message, starting all matching hat threads."""
        for target in self.targets:
            target_hats = target.get_hat_blocks('event_whenbroadcastreceived')
            for bid in target_hats:
                block = target.blocks.get(bid)
                if block:
                    field = block.fields.get('BROADCAST_OPTION')
                    if field and field.value == message:
                        thread = Thread(target=target, top_block=bid)
                        if block.next:
                            thread.top_block = block.next
                        thread.start()
                        self.threads.append(thread)

    # ── Sub-stack execution helper ────────────────────────────────────

    def execute_substack(
        self, target: Target, block_id: str
    ) -> Generator[Any, None, None]:
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
