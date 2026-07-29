"""
Control flow opcodes — ``control_wait``, ``control_repeat``, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target
    from ..types import Block

from ..constants import STOP_ALL, STOP_OTHER_IN_SPRITE, STOP_OTHER_IN_STAGE, STOP_THIS_SCRIPT
from ..thread import YIELD, ThreadStatus, Wait

# ── Counter helpers (stored on the current thread) ─────────────────────


def _get_counter(rt: Runtime) -> int:
    assert rt.current_thread is not None
    return rt.current_thread.counter


def _incr_counter(rt: Runtime) -> None:
    assert rt.current_thread is not None
    rt.current_thread.counter += 1


def _clear_counter(rt: Runtime) -> None:
    assert rt.current_thread is not None
    rt.current_thread.counter = 0


def control_wait(rt: Runtime, tgt: Target, block: Block) -> Any:
    dur = rt.num(tgt, block, "DURATION")
    yield Wait(dur)


def control_repeat(rt: Runtime, tgt: Target, block: Block) -> Any:
    count = rt.num_int(tgt, block, "TIMES")
    sub_id = rt.substack(tgt, block, "SUBSTACK")
    for _ in range(count):
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
        yield YIELD


def control_forever(rt: Runtime, tgt: Target, block: Block) -> Any:
    sub_id = rt.substack(tgt, block, "SUBSTACK")
    while True:
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
        yield YIELD


def control_if(rt: Runtime, tgt: Target, block: Block) -> Any:
    cond = rt.truthy(tgt, block, "CONDITION")
    sub_id = rt.substack(tgt, block, "SUBSTACK")
    if cond and sub_id:
        yield from rt.execute_substack(tgt, sub_id)


def control_if_else(rt: Runtime, tgt: Target, block: Block) -> Any:
    cond = rt.truthy(tgt, block, "CONDITION")
    if cond:
        sub_id = rt.substack(tgt, block, "SUBSTACK")
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
    else:
        sub_id = rt.substack(tgt, block, "SUBSTACK2")
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)


def control_wait_until(rt: Runtime, tgt: Target, block: Block) -> Any:
    while not rt.truthy(tgt, block, "CONDITION"):
        yield YIELD


def control_repeat_until(rt: Runtime, tgt: Target, block: Block) -> Any:
    sub_id = rt.substack(tgt, block, "SUBSTACK")
    while not rt.truthy(tgt, block, "CONDITION"):
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
        yield YIELD


def control_stop(rt: Runtime, tgt: Target, block: Block) -> None:
    """Stop behaviour: stop all | this script | other scripts in sprite | other scripts in stage."""
    choice = rt.field(tgt, block, "STOP_OPTION") or STOP_ALL
    _cur = rt.current_thread
    if choice == STOP_ALL:
        rt.stop_all()
    elif choice == STOP_THIS_SCRIPT:
        if _cur is not None:
            _cur.status = ThreadStatus.DONE
    elif choice == STOP_OTHER_IN_SPRITE:
        for th in rt.threads:
            if th.target is tgt and th is not _cur:
                th.status = ThreadStatus.DONE
    elif choice == STOP_OTHER_IN_STAGE:
        for th in rt.threads:
            if th.target.is_stage and th is not _cur:
                th.status = ThreadStatus.DONE


def control_while(rt: Runtime, tgt: Target, block: Block) -> Any:
    sub_id = rt.substack(tgt, block, "SUBSTACK")
    while rt.truthy(tgt, block, "CONDITION"):
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
        yield YIELD


def control_for_each(rt: Runtime, tgt: Target, block: Block) -> Any:
    var_name = rt.field(tgt, block, "VARIABLE")
    var = tgt.lookup_variable(var_name) if var_name else None
    if var is None:
        return
    from_val = rt.num_int(tgt, block, "FROM")
    to_val = rt.num_int(tgt, block, "TO")
    step = 1 if from_val <= to_val else -1
    for i in range(from_val, to_val + step, step):
        var.value = i
        sub_id = rt.substack(tgt, block, "SUBSTACK")
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
        yield YIELD


def control_get_counter(rt: Runtime, tgt: Target, block: Block) -> Any:
    return _get_counter(rt)


def control_incr_counter(rt: Runtime, tgt: Target, block: Block) -> None:
    _incr_counter(rt)


def control_clear_counter(rt: Runtime, tgt: Target, block: Block) -> None:
    _clear_counter(rt)


def control_create_clone_of(rt: Runtime, tgt: Target, block: Block) -> None:
    """Create a clone of the named sprite."""
    name = rt.field(tgt, block, "CLONE_OPTION")
    if not name:
        name = rt.val(tgt, block, "CLONE_OPTION")
    if name == "_myself_":
        name = tgt.name
    rt.clone_target(name)


def control_delete_this_clone(rt: Runtime, tgt: Target, block: Block) -> None:
    """Delete the current sprite clone."""
    rt.remove_clone(tgt)


def control_start_as_clone(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — fires when a clone is created. Threads started by clone_target."""


def control_all_at_once(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Run the substack without yielding between blocks (all at once)."""
    sub_id = rt.substack(tgt, block, "SUBSTACK")
    if sub_id:
        yield from rt.execute_substack(tgt, sub_id)
