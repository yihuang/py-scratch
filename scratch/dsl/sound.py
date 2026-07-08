"""
Sound category blocks.
"""

from __future__ import annotations

from scratch.vm.types import Field

from .expr import Reporter, StackExpr, _resolve_inputs


def play(name: str | Reporter) -> StackExpr:
    """``sound_play`` — play a sound."""
    ins, shadows = _resolve_inputs({"SOUND_MENU": name})
    return StackExpr(
        opcode="sound_play",
        inputs=ins,
        shadow_reporters=shadows,
    )


def play_until_done(name: str | Reporter) -> StackExpr:
    """``sound_playuntildone`` — play a sound and wait."""
    ins, shadows = _resolve_inputs({"SOUND_MENU": name})
    return StackExpr(
        opcode="sound_playuntildone",
        inputs=ins,
        shadow_reporters=shadows,
    )


def stop_all_sounds() -> StackExpr:
    """``sound_stopallsounds``."""
    return StackExpr(opcode="sound_stopallsounds")


def set_effect(effect: str = "PITCH", value: int | float | Reporter = 0) -> StackExpr:
    """``sound_seteffectto``."""
    ins, shadows = _resolve_inputs({"VALUE": value})
    return StackExpr(
        opcode="sound_seteffectto",
        inputs=ins,
        fields={"EFFECT": Field(value=effect)},
        shadow_reporters=shadows,
    )


def change_effect(effect: str = "PITCH", change: int | float | Reporter = 0) -> StackExpr:
    """``sound_changeeffectby``."""
    ins, shadows = _resolve_inputs({"VALUE": change})
    return StackExpr(
        opcode="sound_changeeffectby",
        inputs=ins,
        fields={"EFFECT": Field(value=effect)},
        shadow_reporters=shadows,
    )


def clear_effects() -> StackExpr:
    """``sound_cleareffects``."""
    return StackExpr(opcode="sound_cleareffects")


def set_volume_to(volume: int | float | Reporter = 100) -> StackExpr:
    """``sound_setvolumeto``."""
    ins, shadows = _resolve_inputs({"VOLUME": volume})
    return StackExpr(
        opcode="sound_setvolumeto",
        inputs=ins,
        shadow_reporters=shadows,
    )


def change_volume_by(change: int | float | Reporter = 0) -> StackExpr:
    """``sound_changevolumeby``."""
    ins, shadows = _resolve_inputs({"VOLUME": change})
    return StackExpr(
        opcode="sound_changevolumeby",
        inputs=ins,
        shadow_reporters=shadows,
    )


def volume() -> Reporter:
    """``sound_volume`` — reporter."""
    return Reporter(opcode="sound_volume")


def set_tempo(tempo: int | float | Reporter = 60) -> StackExpr:
    """``sound_settempo``."""
    ins, shadows = _resolve_inputs({"TEMPO": tempo})
    return StackExpr(
        opcode="sound_settempo",
        inputs=ins,
        shadow_reporters=shadows,
    )


def change_tempo(change: int | float | Reporter = 0) -> StackExpr:
    """``sound_changetempo``."""
    ins, shadows = _resolve_inputs({"TEMPO": change})
    return StackExpr(
        opcode="sound_changetempo",
        inputs=ins,
        shadow_reporters=shadows,
    )


def tempo() -> Reporter:
    """``sound_tempo`` — reporter."""
    return Reporter(opcode="sound_tempo")
