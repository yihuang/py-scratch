"""
Sound opcodes — ``sound_play``, ``sound_playuntildone``, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target
    from ..types import Block

from ..constants import (
    DEFAULT_TEMPO_BPM,
    SOUND_EFFECT_PAN,
    SOUND_EFFECT_PITCH,
    TEMPO_MAX,
    TEMPO_MIN,
    VOLUME_MAX,
    VOLUME_MIN,
)
from ..thread import YIELD
from . import _clamp_effect, _field_val, _find_sound, _ensure_sound_loaded, _str


def sound_sounds_menu(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Menu block: sound name dropdown."""
    name = _field_val(block.fields.get('SOUND_MENU')) if block.fields else ''
    return name


def sound_play(rt: Runtime, tgt: Target, block: Block) -> None:
    """Play a sound (fire-and-forget)."""
    name = _str(rt.val(tgt, block, 'SOUND_MENU'))
    sound_obj = _find_sound(tgt, name)
    if sound_obj is None or not _ensure_sound_loaded(sound_obj):
        return
    channel = sound_obj.sound.play()
    if channel:
        channel.set_volume(max(0.0, min(1.0, tgt.volume / 100.0)))


def sound_playuntildone(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Play a sound and wait until it finishes."""
    name = _str(rt.val(tgt, block, 'SOUND_MENU'))
    sound_obj = _find_sound(tgt, name)
    if sound_obj is None or not _ensure_sound_loaded(sound_obj):
        return
    channel = sound_obj.sound.play()
    if channel:
        channel.set_volume(max(0.0, min(1.0, tgt.volume / 100.0)))
        while channel.get_busy():
            yield YIELD


def sound_stopallsounds(rt: Runtime, tgt: Target, block: Block) -> None:
    """Stop all currently playing sounds."""
    import pygame  # noqa: PLC0415

    if pygame.mixer.get_init():
        pygame.mixer.stop()


def sound_setvolumeto(rt: Runtime, tgt: Target, block: Block) -> None:
    v = max(VOLUME_MIN, min(VOLUME_MAX, rt.num(tgt, block, 'VOLUME')))
    tgt.volume = v


def sound_changevolumeby(rt: Runtime, tgt: Target, block: Block) -> None:
    delta = rt.num(tgt, block, 'VOLUME')
    tgt.volume = max(VOLUME_MIN, min(VOLUME_MAX, tgt.volume + delta))


def sound_volume(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Reporter: current volume."""
    return tgt.volume


def sound_seteffectto(rt: Runtime, tgt: Target, block: Block) -> None:
    effect = _field_val(block.fields.get('EFFECT')) if block.fields else ''
    value = rt.num(tgt, block, 'VALUE')
    if effect in (SOUND_EFFECT_PITCH, SOUND_EFFECT_PAN):
        tgt.sound_effects[effect] = _clamp_effect(effect, value)


def sound_changeeffectby(rt: Runtime, tgt: Target, block: Block) -> None:
    effect = _field_val(block.fields.get('EFFECT')) if block.fields else ''
    delta = rt.num(tgt, block, 'VALUE')
    if effect in (SOUND_EFFECT_PITCH, SOUND_EFFECT_PAN):
        tgt.sound_effects[effect] = _clamp_effect(
            effect, tgt.sound_effects.get(effect, 0.0) + delta
        )


def sound_cleareffects(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.sound_effects = {SOUND_EFFECT_PITCH: 0.0, SOUND_EFFECT_PAN: 0.0}


def sound_settempo(rt: Runtime, tgt: Target, block: Block) -> None:
    bpm = max(TEMPO_MIN, min(TEMPO_MAX, rt.num(tgt, block, 'TEMPO')))
    stage = rt.stage
    if stage:
        stage.tempo = bpm


def sound_changetempo(rt: Runtime, tgt: Target, block: Block) -> None:
    delta = rt.num(tgt, block, 'TEMPO')
    stage = rt.stage
    if stage:
        stage.tempo = max(TEMPO_MIN, min(TEMPO_MAX, stage.tempo + delta))


def sound_tempo(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Reporter: current tempo."""
    stage = rt.stage
    return stage.tempo if stage else DEFAULT_TEMPO_BPM
