"""
Control category blocks — loops, conditionals, waits, cloning.
"""

from __future__ import annotations

from scratch.vm.types import Field

from .expr import Reporter, StackExpr, _resolve_inputs


def repeat(times: int | float | Reporter = 10) -> StackExpr:
    """``control_repeat`` — repeat N times.

    Usage::

        repeat(10)(motion.move(5), ...)
    """
    ins, shadows = _resolve_inputs({'TIMES': times})
    return StackExpr(opcode='control_repeat', inputs=ins, shadow_reporters=shadows)


def forever() -> StackExpr:
    """``control_forever`` — infinite loop.

    Usage::

        forever()(motion.move(5), ...)
    """
    return StackExpr(opcode='control_forever')


def if_(condition: Reporter) -> StackExpr:
    """``control_if``.

    Usage::

        if_(sensing.touching("edge"))(looks.say("ouch"))
    """
    ins, shadows = _resolve_inputs({'CONDITION': condition})
    return StackExpr(opcode='control_if', inputs=ins, shadow_reporters=shadows)


def if_else(condition: Reporter) -> StackExpr:
    """``control_if_else``.

    Usage::

        if_else(cond)(true_branch...).else_(false_branch...)
    """
    ins, shadows = _resolve_inputs({'CONDITION': condition})
    return StackExpr(opcode='control_if_else', inputs=ins, shadow_reporters=shadows)


def wait(duration: int | float | Reporter = 1) -> StackExpr:
    """``control_wait`` — pause for *duration* seconds."""
    ins, shadows = _resolve_inputs({'DURATION': duration})
    return StackExpr(opcode='control_wait', inputs=ins, shadow_reporters=shadows)


def stop(option: str = 'all') -> StackExpr:
    """``control_stop`` — stop *option* ("all", "this script", "other scripts in sprite")."""

    return StackExpr(
        opcode='control_stop',
        fields={'STOP_OPTION': Field(value=option)},
    )


def repeat_until(condition: Reporter) -> StackExpr:
    """``control_repeat_until``.

    Usage::

        repeat_until(cond)(body...)
    """
    ins, shadows = _resolve_inputs({'CONDITION': condition})
    return StackExpr(opcode='control_repeat_until', inputs=ins, shadow_reporters=shadows)


def wait_until(condition: Reporter) -> StackExpr:
    """``control_wait_until``."""
    ins, shadows = _resolve_inputs({'CONDITION': condition})
    return StackExpr(opcode='control_wait_until', inputs=ins, shadow_reporters=shadows)


def create_clone_of(sprite: str) -> StackExpr:
    """``control_create_clone_of``."""

    return StackExpr(
        opcode='control_create_clone_of',
        fields={'CLONE_OPTION': Field(value=sprite)},
    )


def delete_this_clone() -> StackExpr:
    """``control_delete_this_clone``."""
    return StackExpr(opcode='control_delete_this_clone')


def all_at_once() -> StackExpr:
    """``control_all_at_once`` — run without screen refresh."""
    return StackExpr(opcode='control_all_at_once')
