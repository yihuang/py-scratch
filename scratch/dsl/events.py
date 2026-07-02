"""
Events category blocks — hats, broadcasts, and triggers.
"""

from __future__ import annotations

from scratch.vm.types import Field

from .expr import Reporter, StackExpr, _resolve_inputs


def when_flag_clicked() -> StackExpr:
    """``event_whenflagclicked`` — hat block."""
    return StackExpr(opcode='event_whenflagclicked')


def when_key_pressed(key: str = 'space') -> StackExpr:
    """``event_whenkeypressed`` — hat block."""

    return StackExpr(
        opcode='event_whenkeypressed',
        fields={'KEY_OPTION': Field(value=key)},
    )


def when_this_sprite_clicked() -> StackExpr:
    """``event_whenthisspriteclicked`` — hat block."""
    return StackExpr(opcode='event_whenthisspriteclicked')


def when_backdrop_switches_to(backdrop: str = 'next backdrop') -> StackExpr:
    """``event_whenbackdropswitchesto`` — hat block."""

    return StackExpr(
        opcode='event_whenbackdropswitchesto',
        fields={'BACKDROP': Field(value=backdrop)},
    )


def when_greater_than(metric: str = 'loudness', value: int | float | Reporter = 10) -> StackExpr:
    """``event_whengreaterthan`` — hat block.

    *metric* is "loudness" or "timer".
    """

    ins, shadows = _resolve_inputs({'VALUE': value})
    return StackExpr(
        opcode='event_whengreaterthan',
        inputs=ins,
        fields={'WHENGREATERTHAN_MENU': Field(value=metric)},
        shadow_reporters=shadows,
    )


def when_broadcast_received(message: str = '') -> StackExpr:
    """``event_whenbroadcastreceived`` — hat block."""

    return StackExpr(
        opcode='event_whenbroadcastreceived',
        fields={'BROADCAST_OPTION': Field(value=message)},
    )


def broadcast(message: str) -> StackExpr:
    """``event_broadcast``."""

    return StackExpr(
        opcode='event_broadcast',
        fields={'BROADCAST_OPTION': Field(value=message)},
    )


def broadcast_and_wait(message: str) -> StackExpr:
    """``event_broadcastandwait``."""

    return StackExpr(
        opcode='event_broadcastandwait',
        fields={'BROADCAST_OPTION': Field(value=message)},
    )
