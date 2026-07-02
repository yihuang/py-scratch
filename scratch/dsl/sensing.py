"""
Sensing category blocks — input, sensors, queries.
"""

from __future__ import annotations

from scratch.vm.types import Field

from .expr import Reporter, StackExpr, _resolve_inputs


# ── Commands ──────────────────────────────────────────────────────────────


def ask_and_wait(question: str | Reporter = "") -> StackExpr:
    """``sensing_askandwait``."""
    ins, shadows = _resolve_inputs({"QUESTION": question})
    return StackExpr(opcode="sensing_askandwait", inputs=ins, shadow_reporters=shadows)


def reset_timer() -> StackExpr:
    """``sensing_resettimer``."""
    return StackExpr(opcode="sensing_resettimer")


# ── Reporters ─────────────────────────────────────────────────────────────


def answer() -> Reporter:
    """``sensing_answer`` — reporter."""
    return Reporter(opcode="sensing_answer")


def mouse_x() -> Reporter:
    """``sensing_mousex`` — reporter."""
    return Reporter(opcode="sensing_mousex")


def mouse_y() -> Reporter:
    """``sensing_mousey`` — reporter."""
    return Reporter(opcode="sensing_mousey")


def mouse_down() -> Reporter:
    """``sensing_mousedown`` — boolean reporter."""
    return Reporter(opcode="sensing_mousedown")


def key_pressed(key: str | Reporter = "space") -> Reporter:
    """``sensing_keypressed`` — boolean reporter.

    *key* can be "space", "a", "left arrow", etc. or a Reporter.
    """
    if isinstance(key, Reporter):
        ins, shadows = _resolve_inputs({"KEY_OPTION": key})
        return Reporter(opcode="sensing_keypressed", inputs=ins, shadow_reporters=shadows)
    else:
        return Reporter(
            opcode="sensing_keypressed",
            fields={"KEY_OPTION": Field(name="KEY_OPTION", value=key)},
        )


def touching(object: str | Reporter = "mouse pointer") -> Reporter:
    """``sensing_touchingobject`` — boolean reporter.

    *object* is "mouse pointer", "edge", or a sprite name.
    """
    if isinstance(object, Reporter):
        ins, shadows = _resolve_inputs({"TOUCHINGOBJECTMENU": object})
        return Reporter(opcode="sensing_touchingobject", inputs=ins, shadow_reporters=shadows)
    else:
        return Reporter(
            opcode="sensing_touchingobject",
            fields={"TOUCHINGOBJECTMENU": Field(name="TOUCHINGOBJECTMENU", value=object)},
        )


def touching_color(color: int | Reporter = 0) -> Reporter:
    """``sensing_touchingcolor`` — boolean reporter.

    *color* is an integer RGB value.
    """
    ins, shadows = _resolve_inputs({"COLOR": color})
    return Reporter(opcode="sensing_touchingcolor", inputs=ins, shadow_reporters=shadows)


def color_is_touching_color(color: int | Reporter, other_color: int | Reporter) -> Reporter:
    """``sensing_coloristouchingcolor`` — boolean reporter."""
    ins, shadows = _resolve_inputs({"COLOR": color, "COLOR2": other_color})
    return Reporter(opcode="sensing_coloristouchingcolor", inputs=ins, shadow_reporters=shadows)


def distance_to(object: str | Reporter = "mouse pointer") -> Reporter:
    """``sensing_distanceto`` — reporter.

    *object* is "mouse pointer" or a sprite name.
    """
    if isinstance(object, Reporter):
        ins, shadows = _resolve_inputs({"DISTANCETOMENU": object})
        return Reporter(opcode="sensing_distanceto", inputs=ins, shadow_reporters=shadows)
    else:
        return Reporter(
            opcode="sensing_distanceto",
            fields={"DISTANCETOMENU": Field(name="DISTANCETOMENU", value=object)},
        )


def timer() -> Reporter:
    """``sensing_timer`` — reporter."""
    return Reporter(opcode="sensing_timer")


def current(unit: str = "year") -> Reporter:
    """``sensing_current`` — reporter.

    *unit* is "year", "month", "date", "dayofweek", "hour", "minute", "second".
    """
    return Reporter(
        opcode="sensing_current",
        fields={"CURRENTMENU": Field(name="CURRENTMENU", value=unit)},
    )


def days_since_2000() -> Reporter:
    """``sensing_dayssince2000`` — reporter."""
    return Reporter(opcode="sensing_dayssince2000")


def loudness() -> Reporter:
    """``sensing_loudness`` — reporter."""
    return Reporter(opcode="sensing_loudness")


def username() -> Reporter:
    """``sensing_username`` — reporter."""
    return Reporter(opcode="sensing_username")
