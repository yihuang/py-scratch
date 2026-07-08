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
from ..constants import (
    BUBBLE_DECIMAL_THRESHOLD,
    BUBBLE_MAX_CHARS,
    LIST_INDEX_ALL,
    LIST_INDEX_ALL_SENTINEL,
    LIST_INDEX_ANY,
    LIST_INDEX_LAST,
    LIST_INDEX_RANDOM,
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


def _num(inp: Any) -> float:
    """Coerce to number, matching Scratch's ``Number()``.

    * Empty string / whitespace-only → 0.
    * ``'Infinity'`` / ``'-Infinity'`` (exact case) → Infinity.
    * ``'NaN'`` (exact case) → NaN.
    * Everything else non-numeric → NaN.

    Scratch's ``Number()`` is case-sensitive: ``Number('Infinity')`` → Infinity,
    but ``Number('INFINITY')`` → NaN → 0.  Python's ``float()`` is
    case-*in*sensitive, so we gate on the exact string.
    """
    if isinstance(inp, str):
        if inp == "Infinity":
            return float("inf")
        if inp == "-Infinity":
            return float("-inf")
        if inp == "NaN":
            return float("nan")
        if inp.strip() == "":
            return 0.0
        # Try numeric parse; if it fails, Scratch returns NaN
        try:
            return float(inp)
        except (ValueError, TypeError):
            return float("nan")
    if inp is None:
        return 0.0
    try:
        return float(inp)
    except (ValueError, TypeError):
        return float("nan")


def _str(inp: Any) -> str:
    if isinstance(inp, float):
        if inp == -0.0:
            inp = 0.0
        s = f"{inp:g}"
        return s
    return str(inp) if inp is not None else ""


def _bool(inp: Any) -> bool:
    if isinstance(inp, str):
        return inp.lower() not in ("", "false", "0")
    return bool(inp)


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


def _scratch_compare(v1: Any, v2: Any) -> int:
    """Scratch comparison: returns -1 / 0 / 1.

    Mirrors ``Cast.compare()`` in scratch-vm:
    - If both values are numeric, compare as numbers.
    - If either converts to NaN (or is None / whitespace), compare
      case-insensitively as strings.
    """
    if v1 is None or (isinstance(v1, str) and v1.strip() == ""):
        n1 = float("nan")
    else:
        n1 = _num(v1)
    if v2 is None or (isinstance(v2, str) and v2.strip() == ""):
        n2 = float("nan")
    else:
        n2 = _num(v2)
    if math.isnan(n1) or math.isnan(n2):
        s1 = str(v1).lower()
        s2 = str(v2).lower()
        if s1 < s2:
            return -1
        if s1 > s2:
            return 1
        return 0
    if n1 == float("inf") and n2 == float("inf"):
        return 0
    if n1 == float("-inf") and n2 == float("-inf"):
        return 0
    if n1 < n2:
        return -1
    if n1 > n2:
        return 1
    return 0


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
    s = _str(requested)
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
    s = _str(val)
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


def _to_list_index(value: Any, length: int) -> int | str | None:
    """Convert a Scratch list index value to a usable index.

    Returns:
      'ALL'  — for the 'all' special value
      int    — a 1-based index clamped to 1..length, or None if invalid
      None   — invalid/unusable
    """
    if isinstance(value, str):
        v = value.lower()
        if v == LIST_INDEX_ALL:
            return LIST_INDEX_ALL_SENTINEL
        if v == LIST_INDEX_LAST:
            return length if length > 0 else None
        if v in (LIST_INDEX_RANDOM, LIST_INDEX_ANY):
            return random.randint(1, max(1, length))
    try:
        idx = int(round(float(value)))
    except (ValueError, TypeError):
        return None
    if 1 <= idx <= length:
        return idx
    return None
