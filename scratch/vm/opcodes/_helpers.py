"""
Shared helper functions for opcode handlers.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target

from ..types import Input
from ..cast import to_string
from ..constants import (
    BUBBLE_DECIMAL_THRESHOLD,
    BUBBLE_MAX_CHARS,
    PAN_MAX,
    PAN_MIN,
    PITCH_MAX,
    PITCH_MIN,
    SOUND_EFFECT_PAN,
    SOUND_EFFECT_PITCH,
    STAGE_BOTTOM,
    STAGE_LEFT,
    STAGE_RIGHT,
    STAGE_TOP,
)

import pygame


def _field_val(field: Any) -> str:
    if field is None:
        return ""
    if hasattr(field, "value"):
        return str(field.value)
    return str(field)


def _substack_val(inp: Any) -> str | None:
    if inp is None:
        return None
    if isinstance(inp, Input):
        v = inp.value
    else:
        v = inp
    return str(v) if v else None


# ── Motion helpers ───────────────────────────────────────────────────────


def _target_xy(rt: Runtime, target_name: str) -> tuple[float, float] | None:
    """Resolve a target name to (x, y) for go-to / point-towards."""
    if target_name == "_mouse_":
        return (rt.mouse_x(), rt.mouse_y())
    if target_name == "_random_":
        return (
            round(random.uniform(STAGE_LEFT, STAGE_RIGHT)),
            round(random.uniform(STAGE_BOTTOM, STAGE_TOP)),
        )
    t = rt.get_target_by_name(target_name)
    if t is not None:
        return (t.x, t.y)
    return None


# ── Sensing helpers ──────────────────────────────────────────────────────


def _touching_object_check(rt: Runtime, tgt: Target, obj_name: str) -> bool:
    """Check if ``tgt`` is touching ``obj_name`` (_mouse_, _edge_, or sprite name)."""
    if obj_name == "_mouse_":
        return False
    if obj_name == "_edge_":
        left_, top_, right_, bottom_ = tgt.scratch_bounds()
        return (
            tgt.x + left_ < STAGE_LEFT
            or tgt.x + right_ > STAGE_RIGHT
            or tgt.y + bottom_ < STAGE_BOTTOM
            or tgt.y + top_ > STAGE_TOP
        )
    tgt_bounds = tgt.scratch_bounds()
    for other in rt.sprite_targets():
        if other.name != obj_name:
            continue
        other_bounds = other.scratch_bounds()
        if (
            tgt.x + tgt_bounds[0] < other.x + other_bounds[2]
            and tgt.x + tgt_bounds[2] > other.x + other_bounds[0]
            and tgt.y + tgt_bounds[1] > other.y + other_bounds[3]
            and tgt.y + tgt_bounds[3] < other.y + other_bounds[1]
        ):
            return True
    return False


# ── Looks helpers ────────────────────────────────────────────────────────


def _set_costume(tgt: Target, requested: Any) -> None:
    """Scratch-compatible costume/backdrop selection.

    Mirrors official ``_setCostume``:
    - Numbers → 1-based index (always)
    - Strings → try name match, then 'next costume'/'previous costume',
      then number parse
    - NaN/Infinity/True → first costume
    - False/0 → last costume
    - Whitespace → no-op
    - Negative wrap, over-large wrap.
    """
    n = len(tgt.costumes)
    if n == 0:
        return
    if isinstance(requested, bool):
        idx = 0 if requested else n - 1
        tgt.costume_index = idx
        return
    if isinstance(requested, (int, float)):
        if math.isnan(requested) or math.isinf(requested):
            idx = 0
        else:
            idx = int(requested) - 1
        idx %= n
        tgt.costume_index = idx
        return
    s = to_string(requested)
    if s.strip() == "":
        return
    for i, c in enumerate(tgt.costumes):
        if c.name == s:
            tgt.costume_index = i
            return
    if s == "next costume":
        return
    if s == "previous costume":
        return
    try:
        parsed = float(s)
        if math.isnan(parsed) or math.isinf(parsed):
            idx = 0
        else:
            idx = int(parsed) - 1
        idx %= n
        tgt.costume_index = idx
    except (ValueError, TypeError):
        pass


def _set_backdrop(rt: Runtime, val: Any) -> list[Any]:
    """Switch backdrop on the stage and trigger ``event_whenbackdropswitchesto`` hats.

    Returns the list of threads started by the hat.
    """
    stage = rt.stage
    if stage is None:
        return []
    s = to_string(val)
    n = len(stage.costumes)
    if n == 0:
        return []
    old_idx = stage.costume_index
    for i, c in enumerate(stage.costumes):
        if c.name == s:
            stage.costume_index = i
            break
    else:
        if s == "next backdrop":
            stage.costume_index = (stage.costume_index + 1) % n
        elif s == "previous backdrop":
            stage.costume_index = (stage.costume_index - 1) % n
        elif s == "random backdrop" and n > 1:
            idx = stage.costume_index
            while idx == stage.costume_index:
                idx = random.randint(0, n - 1)
            stage.costume_index = idx
        else:
            _set_costume(stage, val)
    if stage.costume_index != old_idx:
        return rt.start_hat("event_whenbackdropswitchesto")
    return []


def _format_bubble_text(text: Any) -> str:
    """Scratch-compatible bubble text formatting.

    - Numbers rounded to 2 decimal places (unless < 0.01 or integer).
    - Truncated at 330 characters.
    """
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        if text % 1 == 0:
            s = str(int(text))
        elif abs(text) >= BUBBLE_DECIMAL_THRESHOLD:
            s = f"{text:.2f}"
        else:
            s = str(text)
    else:
        s = str(text) if text is not None else ""
    return s[:BUBBLE_MAX_CHARS]


# ── Sound helpers ────────────────────────────────────────────────────────


def _find_sound(tgt: Target, name: str) -> Any:
    """Find a sound on the target by name."""
    return tgt.find_sound(name)


def _ensure_sound_loaded(sound: Any) -> bool:
    """Ensure the pygame.mixer.Sound is created from raw data."""
    if sound.sound is not None:
        return True
    if not sound.data:
        return False
    try:
        sound.sound = pygame.mixer.Sound(buffer=sound.data)
        return True
    except Exception:
        return False


def _clamp_effect(effect: str, value: float) -> float:
    """Clamp a sound effect value."""
    if effect == SOUND_EFFECT_PITCH:
        return max(PITCH_MIN, min(PITCH_MAX, value))
    if effect == SOUND_EFFECT_PAN:
        return max(PAN_MIN, min(PAN_MAX, value))
    return value


# ── Data helpers ─────────────────────────────────────────────────────────

LIST_ITEM_LIMIT = 200000
