"""
Motion category blocks.
"""

from __future__ import annotations

from scratch.vm.types import Field

from .expr import Reporter, StackExpr, _resolve_inputs


def move(steps: int | float | Reporter = 10) -> StackExpr:
    """``motion_movesteps``."""
    ins, shadows = _resolve_inputs({'STEPS': steps})
    return StackExpr(opcode='motion_movesteps', inputs=ins, shadow_reporters=shadows)


def turn_right(degrees: int | float | Reporter = 15) -> StackExpr:
    """``motion_turnright``."""
    ins, shadows = _resolve_inputs({'DEGREES': degrees})
    return StackExpr(opcode='motion_turnright', inputs=ins, shadow_reporters=shadows)


def turn_left(degrees: int | float | Reporter = 15) -> StackExpr:
    """``motion_turnleft``."""
    ins, shadows = _resolve_inputs({'DEGREES': degrees})
    return StackExpr(opcode='motion_turnleft', inputs=ins, shadow_reporters=shadows)


def goto(x: int | float | Reporter = 0, y: int | float | Reporter = 0) -> StackExpr:
    """``motion_gotoxy``."""
    ins, shadows = _resolve_inputs({'X': x, 'Y': y})
    return StackExpr(opcode='motion_gotoxy', inputs=ins, shadow_reporters=shadows)


def glide(
    secs: int | float | Reporter = 1, x: int | float | Reporter = 0, y: int | float | Reporter = 0
) -> StackExpr:
    """``motion_glidesecstoxy``."""
    ins, shadows = _resolve_inputs({'SECS': secs, 'X': x, 'Y': y})
    return StackExpr(opcode='motion_glidesecstoxy', inputs=ins, shadow_reporters=shadows)


def glide_to(random_position: str | None = None) -> StackExpr:
    """``motion_glideto`` — glide to a named position or to a sprite.

    *random_position* is e.g. "random position", "mouse pointer", or a sprite name.
    """

    return StackExpr(
        opcode='motion_glideto',
        fields={'TO': Field(value=random_position or 'random position')},
    )


def set_x(x: int | float | Reporter = 0) -> StackExpr:
    """``motion_setx``."""
    ins, shadows = _resolve_inputs({'X': x})
    return StackExpr(opcode='motion_setx', inputs=ins, shadow_reporters=shadows)


def set_y(y: int | float | Reporter = 0) -> StackExpr:
    """``motion_sety``."""
    ins, shadows = _resolve_inputs({'Y': y})
    return StackExpr(opcode='motion_sety', inputs=ins, shadow_reporters=shadows)


def change_x(dx: int | float | Reporter = 10) -> StackExpr:
    """``motion_changexby``."""
    ins, shadows = _resolve_inputs({'DX': dx})
    return StackExpr(opcode='motion_changexby', inputs=ins, shadow_reporters=shadows)


def change_y(dy: int | float | Reporter = 10) -> StackExpr:
    """``motion_changeyby``."""
    ins, shadows = _resolve_inputs({'DY': dy})
    return StackExpr(opcode='motion_changeyby', inputs=ins, shadow_reporters=shadows)


def if_on_edge_bounce() -> StackExpr:
    """``motion_ifonedgebounce``."""
    return StackExpr(opcode='motion_ifonedgebounce')


def set_rotation_style(style: str = 'all around') -> StackExpr:
    """``motion_setrotationstyle`` — *style* is "all around", "left-right", or "don't rotate"."""

    return StackExpr(
        opcode='motion_setrotationstyle',
        fields={'STYLE': Field(value=style)},
    )


def set_direction(direction: int | float | Reporter = 90) -> StackExpr:
    """``motion_setdirection``."""
    ins, shadows = _resolve_inputs({'DIRECTION': direction})
    return StackExpr(opcode='motion_setdirection', inputs=ins, shadow_reporters=shadows)


def point_towards(towards: str = 'mouse pointer') -> StackExpr:
    """``motion_pointtowards`` — *towards* is "mouse pointer" or a sprite name."""

    return StackExpr(
        opcode='motion_pointtowards',
        fields={'TOWARDS': Field(value=towards)},
    )


# ── Reporters ─────────────────────────────────────────────────────────────


def x_position() -> Reporter:
    """``motion_xposition`` — reporter."""
    return Reporter(opcode='motion_xposition')


def y_position() -> Reporter:
    """``motion_yposition`` — reporter."""
    return Reporter(opcode='motion_yposition')


def direction() -> Reporter:
    """``motion_direction`` — reporter."""
    return Reporter(opcode='motion_direction')
