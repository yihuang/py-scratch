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
from typing import Any, Iterable
from .target import Target
from .thread import (
    Thread,
    ThreadStatus,
    Wait,
    YIELD,
    YieldPass,
)
from .constants import (
    CLICK_HIT_RADIUS,
    CLONE_START_HATS,
    PrimitiveType,
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


def _unwrap_shadow(value: Any) -> Any:
    """If *value* is a shadow pair ``[block_id, literal]``, return the literal.
    Otherwise return *value* unchanged."""
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and isinstance(value[1], (int, float, str, bool))
    ):
        return value[1]
    return value


def _input_raw(block: Block, name: str) -> Any:
    """Unwrap a block input to its raw value (literal or block-id string).

    Returns ``None`` if *name* is not present.
    """
    inp = block.inputs.get(name)
    if inp is None:
        return None
    return inp.value if isinstance(inp, Input) else inp


# ── Runtime ──────────────────────────────────────────────────────────────


class Runtime:
    """The central runtime: holds targets, runs threads, dispatches opcodes."""

    def __init__(self) -> None:
        self.targets: list[Target] = []
        self._runnable_queue: list[Thread] = []
        self._handlers: dict[str, Handler] = {}
        self.clock = Clock()
        self.stage: Target | None = None
        self._keyboard: dict[str, bool] = {}
        self._wait_queue: list[tuple[float, int, Thread]] = []
        self._wait_seq = 0
        self.current_thread: Thread | None = None
        self._answer: str | None = None
        self._for_each_counter: float = 0
        self._real_time: bool = True
        self._time = time
        self._clones: list[Target] = []
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0
        self._mouse_down: bool = False
        self._edge_hat_values: dict[str, bool] = {}
        self._cloud_count: int = 0
        self._cloud_limit: int = 10
        self._cloud: Any = None

    @property
    def threads(self) -> list[Thread]:
        """All alive threads: runnable + waiting.  Read-only view for external consumers."""
        waiting = [t for _, _, t in self._wait_queue]
        return self._runnable_queue + waiting

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

    # ── Cloud IO ─────────────────────────────────────────────────────

    def _init_cloud(self) -> None:
        """Lazily create the Cloud IO device."""
        if self._cloud is None:
            from .cloud import Cloud  # noqa: PLC0415  — late import to avoid circular dependency

            self._cloud = Cloud(self)
            if self.stage is not None:
                self._cloud.set_stage(self.stage)

    def io_query(self, device: str, method: str, *args: Any) -> Any:
        """Query an IO device (cloud, keyboard, etc.)."""
        if device == 'cloud':
            self._init_cloud()
            fn = getattr(self._cloud, method, None)
            if fn is not None:
                return fn(*args)
        return None

    def can_add_cloud_variable(self) -> bool:
        """Check if another cloud variable can be added (max 10)."""
        return self._cloud_count < self._cloud_limit

    def add_cloud_variable(self) -> None:
        """Increment the cloud variable counter."""
        self._cloud_count += 1

    def has_cloud_data(self) -> bool:
        """Whether the runtime has any cloud variables."""
        return self._cloud_count > 0

    def add_target(self, target: Target) -> None:
        self.targets.append(target)
        if target.is_stage:
            self.stage = target
            self._init_cloud()
            if self._cloud is not None:
                self._cloud.set_stage(self.stage)
        target._rebuild_hat_cache()

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
        clone._rebuild_hat_cache()
        # Start all hat scripts on the clone (only control_start_as_clone per official impl)
        for opcode in CLONE_START_HATS:
            self.start_threads(clone, clone.get_hat_next_blocks(opcode))
        return clone


    def remove_clone(self, clone: Target) -> None:
        """Remove a clone from the runtime."""
        if clone._is_clone and clone in self._clones:
            self._clones.remove(clone)
            self.targets.remove(clone)
            self._runnable_queue[:] = [t for t in self._runnable_queue if t.target is not clone]
            self._wait_queue[:] = [e for e in self._wait_queue if e[2].target is not clone]

    # ── Input evaluation ──────────────────────────────────────────────

    def evaluate(self, target: Target, block_id: str) -> Any:
        """Evaluate a reporter/boolean block by id and return its value.

        Reporters are synchronous — they return their value directly.
        """
        block = target.blocks[block_id]
        handler = self.get_handler(block.opcode)
        if handler is None:
            return None
        return handler(self, target, block)

    def resolve_input(self, target: Target, value: Any) -> Any:
        """Resolve a raw value (literal, block reference, or inlined primitive) to a concrete value.

        The caller is responsible for stripping the ``Input`` wrapper first
        via ``_input_raw``.
        """
        if isinstance(value, str) and value in target.blocks:
            return self.evaluate(target, value)

        # Scratch inlined primitive: [type_code, value, ...]
        if isinstance(value, (list, tuple)) and len(value) >= 2 and isinstance(value[0], int):
            type_code = value[0]
            ref = value[1]
            if type_code == PrimitiveType.VARIABLE:  # Variable reference
                var = target.lookup_variable(ref) or (
                    self.stage and self.stage.lookup_variable(ref)
                )
                return var.value if var else 0
            if type_code == PrimitiveType.LIST:  # List reference
                lst = target.lookup_list(ref) or (self.stage and self.stage.lookup_list(ref))
                return lst.contents if lst else []
            # Literal primitives (4-10) and broadcast (11) — return the value directly
            return ref

        # Shadow pair: [block_id, literal] — use the literal.
        return _unwrap_shadow(value)

    def resolve_bool(self, target: Target, inp: Input | Any) -> bool:
        """Resolve a boolean-typed input."""
        v = self.resolve_input(target, inp)
        if isinstance(v, str):
            return v.lower() not in ('', 'false', '0')
        return bool(v)

    def resolve_num(self, target: Target, inp: Input | Any) -> float:
        """Resolve a numeric input — non-numeric values coerce to 0."""
        try:
            return float(self.resolve_input(target, inp) or 0)
        except (ValueError, TypeError):
            return 0.0

    def num(self, target: Target, block: Block, name: str) -> float:
        """Resolve a named numeric input from *block*."""
        return self.resolve_num(target, _input_raw(block, name))

    def num_int(self, target: Target, block: Block, name: str) -> int:
        """Resolve a named numeric input and round to nearest int (Scratch-style round-half-up)."""
        return int(self.num(target, block, name) + 0.5)

    def truthy(self, target: Target, block: Block, name: str) -> bool:
        """Resolve a named boolean input from *block*."""
        return self.resolve_bool(target, _input_raw(block, name))

    def val(self, target: Target, block: Block, name: str) -> Any:
        """Resolve a named arbitrary input from *block*."""
        return self.resolve_input(target, _input_raw(block, name))

    # ── Thread lifecycle ──────────────────────────────────────────────

    def start_threads(self, target: Target, block_ids: Iterable[str]) -> list[Thread]:
        """Start threads at the given block IDs (usually hat blocks)."""
        created: list[Thread] = []
        for bid in block_ids:
            thread = Thread(target=target, top_block=bid)
            thread.start()
            self._runnable_queue.append(thread)
            created.append(thread)
        return created

    def start_hat(self, opcode: str) -> list[Thread]:
        """Start threads for all hat blocks with the given opcode."""
        created: list[Thread] = []
        for target in self.targets:
            created += self.start_threads(target, target.get_hat_next_blocks(opcode))
        return created

    def start_hat_for(self, opcode: str, target: Target) -> list[Thread]:
        """Start threads for all hat blocks with the given opcode on a specific target."""
        return self.start_threads(target, target.get_hat_next_blocks(opcode))

    def start_key_hat(self, key_name: str) -> None:
        for target in self.targets:
            for block in target.get_hat_blocks('event_whenkeypressed'):
                if block.next is None:
                    continue

                # TODO cleanup field parsing
                fld = block.fields.get('KEY_OPTION')
                hat_key = str(getattr(fld, 'value', fld or ''))
                if hat_key != 'any' and hat_key != key_name:
                    continue
                thread = Thread(target=target, top_block=block.next)
                thread.start()
                self._runnable_queue.append(thread)

    def start_click_hat(self, scratch_x: float, scratch_y: float) -> None:
        """Start click hats for the sprite (or stage) at *(scratch_x, scratch_y)*."""
        # Hit-test sprites in reverse layer order (topmost first)
        sprites = sorted(self.sprite_targets(), key=lambda t: t.layer_order, reverse=True)
        for tgt in sprites:
            if not tgt.visible:
                continue

            # Simple radius check: bounding circle based on costume size
            radius = CLICK_HIT_RADIUS
            if tgt.costume and tgt.costume.surface:
                w, h = tgt.costume.surface.get_size()
                radius = (math.sqrt(w * w + h * h) / 2) * (tgt.size / 100.0)
            dx = scratch_x - tgt.x
            dy = scratch_y - tgt.y
            if dx * dx + dy * dy <= radius * radius:
                self.start_hat_for('event_whenthisspriteclicked', tgt)
                return

        # No sprite hit — stage click
        if self.stage is not None:
            self.start_hat_for('event_whenstageclicked', self.stage)

    def _check_edge_hat(
        self, opcode: str, target: Target, block: Block, current_value: bool
    ) -> bool:
        """Check false→true edge activation for edge-activated hats.

        Returns True only when *current_value* is True and the previous
        stored value for this hat instance was False.
        """
        key = f'{opcode}:{id(target)}:{block.id}'
        prev = self._edge_hat_values.get(key, False)
        self._edge_hat_values[key] = current_value
        return current_value and not prev

    # ── Scheduler ─────────────────────────────────────────────────────

    def step(self) -> None:
        # 1. Wake waiting threads whose timer expired
        now = self._time.monotonic() if self._real_time else self.clock._tick
        while self._wait_queue and self._wait_queue[0][0] <= now:
            _, _, thread = heapq.heappop(self._wait_queue)
            if thread.status == ThreadStatus.WAITING:
                thread.status = ThreadStatus.RUNNING
                self._runnable_queue.append(thread)

        # 2. Step each runnable thread once.
        #    Post-step: done threads are dropped, waiting threads stay in _wait_queue.
        still_runnable: list[Thread] = []
        for thread in self._runnable_queue:
            if thread.is_done():
                continue  # marked done externally (stop opcode, etc.)
            self._step_thread(thread)
            if not thread.is_done() and thread.status != ThreadStatus.WAITING:
                still_runnable.append(thread)
        self._runnable_queue[:] = still_runnable

        self.clock.tick()

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
                if thread.status is ThreadStatus.DONE:
                    self.current_thread = None
                    return
                self._advance_to_next(thread)
                self.current_thread = None
                return
            if isinstance(gen_or_val, types.GeneratorType):
                frame.gen = gen_or_val
            else:
                # Non-generator with __next__ (unusual) — treat as instant
                if thread.status is ThreadStatus.DONE:
                    self.current_thread = None
                    return
                self._advance_to_next(thread)
                self.current_thread = None
                return
        try:
            yielded = next(frame.gen)
        except StopIteration:
            if thread.status is ThreadStatus.DONE:
                self.current_thread = None
                return
            self._advance_to_next(thread)
            self.current_thread = None
            return
        match yielded:
            case Wait(seconds=secs):
                self._schedule_wake(thread, secs)
                self.current_thread = None
                return
            case YieldPass():
                self.current_thread = None
                return
            case _:
                raise RuntimeError(
                    f'Unknown yield {yielded!r} from {block.opcode!r} (block {block.id!r})'
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
        self._runnable_queue.clear()
        self._wait_queue.clear()
        self.start_hat('event_whenflagclicked')

    def broadcast(self, message: str) -> list[Thread]:
        started: list[Thread] = []
        for target in self.targets:
            for block in target.get_hat_blocks('event_whenbroadcastreceived'):
                if not block.next:
                    continue

                # TODO parse field value
                fld = block.fields.get('BROADCAST_OPTION')
                hat_val = str(getattr(fld, 'value', fld or ''))
                # Match: try broadcast id/name lookup, fall back to direct string comparison
                matched = False
                if hat_val == message:
                    matched = True
                else:
                    for bcast_id, bcast_msg in target.broadcasts.items():
                        if hat_val == bcast_id or hat_val == bcast_msg.name:
                            if message == bcast_id or message == bcast_msg.name:
                                matched = True
                            break
                if not matched:
                    continue

                thread = Thread(target=target, top_block=block.next)
                thread.start()
                self._runnable_queue.append(thread)
                started.append(thread)
        return started

    # ── Sub-stack execution helper ────────────────────────────────────

    def execute_substack(
        self, target: Target, block_id: str | None, yield_between: bool = True
    ) -> Generator[Any]:
        """Generator: step through a linked list of blocks.

        Control blocks (repeat, if, etc.) should ``yield from`` this
        to execute their substack input.

        Set *yield_between* to False to run all blocks atomically without
        yielding control between consecutive blocks.
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
                if bid and yield_between:
                    yield YIELD
                continue
            try:
                while True:
                    val = next(gen)
                    yield val
            except StopIteration:
                pass
            bid = block.next
            if bid and yield_between:
                yield YIELD
