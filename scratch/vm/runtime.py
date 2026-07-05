"""
Runtime — the Scratch VM execution engine.

Manages targets, dispatches opcode handlers, and runs threads via the
inherited :class:`Scheduler`.
"""

from __future__ import annotations

import copy
import math
import types
from collections.abc import Callable, Generator
from typing import Any, Iterable, cast

from .target import Target
from .thread import Thread, ThreadStatus, Wait, YieldPass
from .scheduler import Scheduler, SchedulerThread
from .constants import CLICK_HIT_RADIUS, CLONE_START_HATS, PrimitiveType
from .types import Block, Input
from .cloud import Cloud

# Type alias: an opcode handler is a generator that yields control signals
# and (for reporters) ends by returning a value.
Handler = Callable[['Runtime', Target, Block], Generator[Any] | None]


# ── Fallback helpers (used by tests) ─────────────────────────────────────


def _unwrap_shadow(value: Any) -> Any:
    """Fallback: if *value* is a ``[string, scalar]`` pair, return the scalar.

    This handles edge cases where a value looks like ``['block_id', 42]``
    but the first element isn't a known primitive type code (4-13) — the
    literal second element is the actual shadow default.

    Compact primitive arrays ``[4, value]`` through ``[13, value]`` are
    NOT affected since they're handled by ``resolve_input``'s type_code branch.
    """
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        # Exclude compact primitives (type codes 4-13)
        and not (isinstance(value[0], int) and 4 <= value[0] <= 13)
        and isinstance(value[1], (int, float, str, bool))
    ):
        return value[1]
    return value


def _input_raw(block: Block, name: str) -> Any:
    """Unwrap a block input to its raw value (literal, block-id string, or
    compact primitive array).

    Returns ``None`` if *name* is not present.
    The caller loses the ``shadow`` flag — use ``_resolve_input`` for
    full resolution (or pass ``is_shadow`` directly).
    """
    inp = block.inputs.get(name)
    if inp is None:
        return None
    return inp.value


# ── Runtime ──────────────────────────────────────────────────────────────


class Runtime(Scheduler):
    """The central runtime: holds targets, dispatches opcodes, runs threads.

    Inherits from :class:`Scheduler` — thread queue management, clock, and
    the main step loop are provided by the parent class.  This class adds
    Scratch-specific logic: opcode dispatch, input evaluation, broadcast,
    and target management.
    """

    def __init__(self) -> None:
        super().__init__()
        self.targets: list[Target] = []
        self._handlers: dict[str, Handler] = {}
        self.stage: Target | None = None
        self.current_thread: Thread | None = None

        # Input/IO state
        self._keyboard: dict[str, bool] = {}
        self._answer: str | None = None
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0
        self._mouse_down: bool = False
        self._edge_hat_values: dict[str, bool] = {}
        self._for_each_counter: float = 0
        self._cloud: Any = None
        self._cloud_count: int = 0
        self._cloud_limit: int = 10
        self._clones: list[Target] = []

    @property
    def threads(self) -> list[Thread]:  # type: ignore[override]
        """All alive threads: runnable + waiting (read-only view)."""
        return cast(list[Thread], super().threads)

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

    # ── Target management ─────────────────────────────────────────────

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
        for opcode in CLONE_START_HATS:
            self.start_threads(clone, clone.get_hat_next_blocks(opcode))
        return clone

    def remove_clone(self, clone: Target) -> None:
        """Remove a clone from the runtime."""
        if clone._is_clone and clone in self._clones:
            self._clones.remove(clone)
            self.targets.remove(clone)
            self.remove_threads_for(clone)

    # ── Input evaluation ──────────────────────────────────────────────

    def evaluate(self, target: Target, block_id: str) -> Any:
        """Evaluate a reporter/boolean block by id and return its value."""
        block = target.blocks[block_id]
        handler = self.get_handler(block.opcode)
        if handler is None:
            return None
        return handler(self, target, block)

    def resolve_input(self, target: Target, value: Any, is_shadow: bool = False) -> Any:
        """Resolve a raw value to a concrete runtime value."""
        if isinstance(value, str) and not is_shadow and value in target.blocks:
            return self.evaluate(target, value)

        if isinstance(value, (list, tuple)) and len(value) >= 2 and isinstance(value[0], int):
            type_code = value[0]
            ref = value[1]
            if type_code == PrimitiveType.VARIABLE:  # 12
                var = target.lookup_variable(ref) or (
                    self.stage and self.stage.lookup_variable(ref)
                )
                return var.value if var else 0
            if type_code == PrimitiveType.LIST:  # 13
                lst = target.lookup_list(ref) or (self.stage and self.stage.lookup_list(ref))
                return lst.contents if lst else []
            if isinstance(ref, str) and ref in target.blocks:
                return self.evaluate(target, ref)
            return ref

        return _unwrap_shadow(value)

    def resolve_bool(self, target: Target, value: Any) -> bool:
        v = self.resolve_input(target, value)
        if isinstance(v, str):
            return v.lower() not in ('', 'false', '0')
        return bool(v)

    def resolve_num(self, target: Target, value: Any) -> float:
        try:
            return float(self.resolve_input(target, value) or 0)
        except (ValueError, TypeError):
            return 0.0

    def _input_value(self, block: Block, name: str) -> tuple[Any, bool]:
        inp = block.inputs.get(name)
        if inp is None:
            return None, False
        if isinstance(inp, Input):
            return inp.value, inp.shadow
        return inp, False

    def num(self, target: Target, block: Block, name: str) -> float:
        value, _is_shadow = self._input_value(block, name)
        return self.resolve_num(target, value)

    def num_int(self, target: Target, block: Block, name: str) -> int:
        val = self.num(target, block, name)
        if not math.isfinite(val):
            return 0
        return int(val + 0.5)

    def truthy(self, target: Target, block: Block, name: str) -> bool:
        value, is_shadow = self._input_value(block, name)
        v = self.resolve_input(target, value, is_shadow=is_shadow)
        if isinstance(v, str):
            return v.lower() not in ('', 'false', '0')
        return bool(v)

    def val(self, target: Target, block: Block, name: str) -> Any:
        value, is_shadow = self._input_value(block, name)
        return self.resolve_input(target, value, is_shadow=is_shadow)

    # ── Thread lifecycle ──────────────────────────────────────────────

    def start_threads(self, target: Target, block_ids: Iterable[str]) -> list[Thread]:
        """Start threads at the given block IDs (usually hat blocks)."""
        created: list[Thread] = []
        for bid in block_ids:
            thread = Thread(target=target, top_block=bid)
            thread.start()
            self.resume(thread)
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
                fld = block.fields.get('KEY_OPTION')
                hat_key = str(getattr(fld, 'value', fld or ''))
                if hat_key != 'any' and hat_key != key_name:
                    continue
                thread = Thread(target=target, top_block=block.next)
                thread.start()
                self.resume(thread)

    def start_click_hat(self, scratch_x: float, scratch_y: float) -> None:
        """Start click hats for the sprite (or stage) at *(scratch_x, scratch_y)*."""
        sprites = sorted(self.sprite_targets(), key=lambda t: t.layer_order, reverse=True)
        for tgt in sprites:
            if not tgt.visible:
                continue
            radius = CLICK_HIT_RADIUS
            if tgt.costume and tgt.costume.surface:
                w, h = tgt.costume.surface.get_size()
                radius = (math.sqrt(w * w + h * h) / 2) * (tgt.size / 100.0)
            dx = scratch_x - tgt.x
            dy = scratch_y - tgt.y
            if dx * dx + dy * dy <= radius * radius:
                self.start_hat_for('event_whenthisspriteclicked', tgt)
                return
        if self.stage is not None:
            self.start_hat_for('event_whenstageclicked', self.stage)

    def _check_edge_hat(
        self, opcode: str, target: Target, block: Block, current_value: bool
    ) -> bool:
        """Check false→true edge activation for edge-activated hats."""
        key = f'{opcode}:{id(target)}:{block.id}'
        prev = self._edge_hat_values.get(key, False)
        self._edge_hat_values[key] = current_value
        return current_value and not prev

    # ── Scheduler template method override ────────────────────────────

    def _step_thread(self, thread: SchedulerThread) -> None:
        """Advance one thread by one 'instruction' (template method override)."""
        t = cast(Thread, thread)
        self.current_thread = t
        frame = t.peek_frame()
        if frame is None:
            t.status = ThreadStatus.DONE
            self.current_thread = None
            return
        block = t.target.blocks.get(frame.block_id)
        if block is None:
            t.pop_frame()
            self.current_thread = None
            return
        handler = self.get_handler(block.opcode)
        if handler is None:
            self._advance_to_next(t)
            self.current_thread = None
            return
        if frame.gen is None:
            gen_or_val = handler(self, t.target, block)
            if gen_or_val is None or not hasattr(gen_or_val, '__next__'):
                if t.status is ThreadStatus.DONE:
                    self.current_thread = None
                    return
                self._advance_to_next(t)
                self.current_thread = None
                return
            if isinstance(gen_or_val, types.GeneratorType):
                frame.gen = gen_or_val
            else:
                if t.status is ThreadStatus.DONE:
                    self.current_thread = None
                    return
                self._advance_to_next(t)
                self.current_thread = None
                return
        try:
            yielded = next(frame.gen)
        except StopIteration:
            if t.status is ThreadStatus.DONE:
                self.current_thread = None
                return
            self._advance_to_next(t)
            self.current_thread = None
            return
        match yielded:
            case Wait(seconds=secs):
                self.schedule_wake(t, secs)
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
        """Move the thread's current frame to the next block in the chain."""
        frame = thread.peek_frame()
        if frame is None:
            thread.status = ThreadStatus.DONE
            return
        block = thread.target.blocks.get(frame.block_id)
        if block and block.next:
            frame.block_id = block.next
            frame.gen = None
        else:
            thread.pop_frame()
            if not thread.stack:
                thread.status = ThreadStatus.DONE

    def green_flag(self) -> None:
        """Clear all threads and start ``when flag clicked`` hats."""
        self.clear()
        self.start_hat('event_whenflagclicked')

    def broadcast(self, message: str) -> list[Thread]:
        """Broadcast a message — start all matching ``when I receive`` hats."""
        started: list[Thread] = []
        for target in self.targets:
            for block in target.get_hat_blocks('event_whenbroadcastreceived'):
                if not block.next:
                    continue
                fld = block.fields.get('BROADCAST_OPTION')
                hat_val = str(getattr(fld, 'value', fld or ''))
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
                self.resume(thread)
                started.append(thread)
        return started

    # ── Sub-stack execution helper ────────────────────────────────────

    def execute_substack(self, target: Target, block_id: str | None) -> Generator[Any]:
        """Generator: step through a linked list of blocks atomically.

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
                bid = block.next
                continue
            try:
                while True:
                    val = next(gen)
                    yield val
            except StopIteration:
                pass
            bid = block.next
