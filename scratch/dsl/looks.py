"""
Looks category blocks.
"""

from __future__ import annotations

from scratch.vm.types import Field

from .expr import Reporter, StackExpr, _resolve_inputs
def say(message: str | Reporter = "") -> StackExpr:
    """``looks_say``."""
    ins, shadows = _resolve_inputs({"MESSAGE": message})
    return StackExpr(opcode="looks_say", inputs=ins, shadow_reporters=shadows)


def say_for_seconds(message: str | Reporter = "", secs: int | float | Reporter = 2) -> StackExpr:
    """``looks_sayforsecs``."""
    ins, shadows = _resolve_inputs({"MESSAGE": message, "SECS": secs})
    return StackExpr(opcode="looks_sayforsecs", inputs=ins, shadow_reporters=shadows)


def think(message: str | Reporter = "") -> StackExpr:
    """``looks_think``."""
    ins, shadows = _resolve_inputs({"MESSAGE": message})
    return StackExpr(opcode="looks_think", inputs=ins, shadow_reporters=shadows)


def think_for_seconds(message: str | Reporter = "", secs: int | float | Reporter = 2) -> StackExpr:
    """``looks_thinkforsecs``."""
    ins, shadows = _resolve_inputs({"MESSAGE": message, "SECS": secs})
    return StackExpr(opcode="looks_thinkforsecs", inputs=ins, shadow_reporters=shadows)


def show() -> StackExpr:
    """``looks_show``."""
    return StackExpr(opcode="looks_show")


def hide() -> StackExpr:
    """``looks_hide``."""
    return StackExpr(opcode="looks_hide")


def switch_costume_to(costume: str = "") -> StackExpr:
    """``looks_switchcostumeto``."""

    return StackExpr(
        opcode="looks_switchcostumeto",
        fields={"COSTUME": Field(name="COSTUME", value=costume)},
    )


def next_costume() -> StackExpr:
    """``looks_nextcostume``."""
    return StackExpr(opcode="looks_nextcostume")


def switch_backdrop_to(backdrop: str = "") -> StackExpr:
    """``looks_switchbackdropto``."""

    return StackExpr(
        opcode="looks_switchbackdropto",
        fields={"BACKDROP": Field(name="BACKDROP", value=backdrop)},
    )


def next_backdrop() -> StackExpr:
    """``looks_nextbackdrop``."""
    return StackExpr(opcode="looks_nextbackdrop")


def change_effect(effect: str = "color", change: int | float | Reporter = 25) -> StackExpr:
    """``looks_changeeffectby`` — *effect* is e.g. "color", "fisheye", "whirl", etc."""

    ins, shadows = _resolve_inputs({"CHANGE": change})
    return StackExpr(
        opcode="looks_changeeffectby",
        inputs=ins,
        fields={"EFFECT": Field(name="EFFECT", value=effect)},
        shadow_reporters=shadows,
    )


def set_effect(effect: str = "color", value: int | float | Reporter = 0) -> StackExpr:
    """``looks_seteffectto``."""

    ins, shadows = _resolve_inputs({"VALUE": value})
    return StackExpr(
        opcode="looks_seteffectto",
        inputs=ins,
        fields={"EFFECT": Field(name="EFFECT", value=effect)},
        shadow_reporters=shadows,
    )


def clear_effects() -> StackExpr:
    """``looks_cleargraphiceffects``."""
    return StackExpr(opcode="looks_cleargraphiceffects")


def change_size_by(change: int | float | Reporter = 10) -> StackExpr:
    """``looks_changesizeby``."""
    ins, shadows = _resolve_inputs({"CHANGE": change})
    return StackExpr(opcode="looks_changesizeby", inputs=ins, shadow_reporters=shadows)


def set_size_to(size: int | float | Reporter = 100) -> StackExpr:
    """``looks_setsizeto``."""
    ins, shadows = _resolve_inputs({"SIZE": size})
    return StackExpr(opcode="looks_setsizeto", inputs=ins, shadow_reporters=shadows)


def change_volume_by(change: int | float | Reporter = 10) -> StackExpr:
    """``looks_changevolumeby``."""
    ins, shadows = _resolve_inputs({"VOLUME": change})
    return StackExpr(opcode="looks_changevolumeby", inputs=ins, shadow_reporters=shadows)


def set_volume_to(volume: int | float | Reporter = 100) -> StackExpr:
    """``looks_setvolumeto``."""
    ins, shadows = _resolve_inputs({"VOLUME": volume})
    return StackExpr(opcode="looks_setvolumeto", inputs=ins, shadow_reporters=shadows)


# ── Reporters ─────────────────────────────────────────────────────────────


def costume_number_name() -> Reporter:
    """``looks_costumenumbername`` — returns the current costume index/name number.

    Usage: ``costume_number_name()`` — returns current costume index.
    """
    return Reporter(opcode="looks_costumenumbername")


def size() -> Reporter:
    """``looks_size`` — reporter."""
    return Reporter(opcode="looks_size")


def volume() -> Reporter:
    """``looks_volume`` — reporter."""
    return Reporter(opcode="looks_volume")
