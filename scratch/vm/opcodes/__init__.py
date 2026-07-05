"""
Opcode handlers — dispatched by :class:`scratch.vm.runtime.Runtime`.

Each handler is a function ``(runtime, target, block)``:

* **Stack blocks** that need to pause ``yield YIELD`` or ``yield Wait(secs)``.
* **Reporter blocks** ``return`` their value directly (no ``yield``).
* **Instant (no-op) handlers** return ``None``.

The handlers are organised by category into sub-modules and collected
into the :data:`OPCODE_MAP` registry.
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

# ═════════════════════════════════════════════════════════════════════════
#  Shared helpers
# ═════════════════════════════════════════════════════════════════════════

__all__: list[str] = [
    'OPCODE_MAP',
]


def _num(inp: Any) -> float:
    """Coerce to number; Scratch treats non-numeric as 0.

    Scratch's ``Number()`` is case-sensitive: ``Number('Infinity')`` → Infinity,
    but ``Number('INFINITY')`` → NaN → 0.  Python's ``float()`` is
    case-*in*sensitive, so we gate on the exact string.
    """
    if isinstance(inp, str):
        if inp == 'Infinity':
            return float('inf')
        if inp == '-Infinity':
            return float('-inf')
    try:
        return float(inp)
    except (ValueError, TypeError):
        return 0.0


def _str(inp: Any) -> str:
    if isinstance(inp, float):
        if inp == -0.0:
            inp = 0.0
        s = f'{inp:g}'
        return s
    return str(inp) if inp is not None else ''


def _bool(inp: Any) -> bool:
    if isinstance(inp, str):
        return inp.lower() not in ('', 'false', '0')
    return bool(inp)


def _field_val(field: Any) -> str:
    if field is None:
        return ''
    if hasattr(field, 'value'):
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
    if v1 is None or (isinstance(v1, str) and v1.strip() == ''):
        n1 = float('nan')
    else:
        n1 = _num(v1)
    if v2 is None or (isinstance(v2, str) and v2.strip() == ''):
        n2 = float('nan')
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
    if n1 == float('inf') and n2 == float('inf'):
        return 0
    if n1 == float('-inf') and n2 == float('-inf'):
        return 0
    if n1 < n2:
        return -1
    if n1 > n2:
        return 1
    return 0


# ── Motion helpers ───────────────────────────────────────────────────────


def _target_xy(rt: Runtime, target_name: str) -> tuple[float, float] | None:
    """Resolve a target name to (x, y) for go-to / point-towards."""
    if target_name == '_mouse_':
        return (rt._mouse_x, rt._mouse_y)
    if target_name == '_random_':
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
    if obj_name == '_mouse_':
        return False
    if obj_name == '_edge_':
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
    if s.strip() == '':
        return
    for i, c in enumerate(tgt.costumes):
        if c.name == s:
            tgt.costume_index = i
            return
    if s == 'next costume':
        return
    if s == 'previous costume':
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
        if s == 'next backdrop':
            stage.costume_index = (stage.costume_index + 1) % n
        elif s == 'previous backdrop':
            stage.costume_index = (stage.costume_index - 1) % n
        elif s == 'random backdrop' and n > 1:
            idx = stage.costume_index
            while idx == stage.costume_index:
                idx = random.randint(0, n - 1)
            stage.costume_index = idx
        else:
            _set_costume(stage, val)
    if stage.costume_index != old_idx:
        return rt.start_hat('event_whenbackdropswitchesto')
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
            s = f'{text:.2f}'
        else:
            s = str(text)
    else:
        s = str(text) if text is not None else ''
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
        import pygame  # noqa: PLC0415

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


# ═════════════════════════════════════════════════════════════════════════
#  Import category modules & assemble OPCODE_MAP
# ═════════════════════════════════════════════════════════════════════════

from .control import (  # noqa: E402  # isort: skip
    control_all_at_once,
    control_clear_counter,
    control_create_clone_of,
    control_delete_this_clone,
    control_for_each,
    control_forever,
    control_get_counter,
    control_if,
    control_if_else,
    control_incr_counter,
    control_repeat,
    control_repeat_until,
    control_start_as_clone,
    control_stop,
    control_wait,
    control_wait_until,
    control_while,
)

from .event import (  # noqa: E402  # isort: skip
    event_broadcast,
    event_broadcastandwait,
    event_whenbackdropswitchesto,
    event_whenbroadcastreceived,
    event_whenflagclicked,
    event_whengreaterthan,
    event_whenkeypressed,
    event_whenstageclicked,
    event_whenthisspriteclicked,
    event_whentouchingobject,
)

from .motion import (  # noqa: E402  # isort: skip
    motion_align_scene,
    motion_changexby,
    motion_changeyby,
    motion_direction,
    motion_glideto,
    motion_glideto_menu,
    motion_glidesecstoxy,
    motion_goto,
    motion_gotoxy,
    motion_gox,
    motion_goy,
    motion_ifonedgebounce,
    motion_movesteps,
    motion_pointindirection,
    motion_pointtowards,
    motion_scroll_right,
    motion_scroll_up,
    motion_setdirection,
    motion_setrotationstyle,
    motion_setx,
    motion_sety,
    motion_turnleft,
    motion_turnright,
    motion_xposition,
    motion_xscroll,
    motion_yposition,
    motion_yscroll,
)

from .looks import (  # noqa: E402  # isort: skip
    looks_backdropnumbername,
    looks_backdrops,
    looks_changeeffectby,
    looks_changesizeby,
    looks_changestretchby,
    looks_cleargraphiceffects,
    looks_costume,
    looks_costumenumbername,
    looks_goforwardbackwardlayers,
    looks_gotofrontback,
    looks_hide,
    looks_hideallsprites,
    looks_nextbackdrop,
    looks_nextcostume,
    looks_say,
    looks_sayforsecs,
    looks_seteffectto,
    looks_setsizeto,
    looks_setstretchto,
    looks_show,
    looks_size,
    looks_switchbackdropto,
    looks_switchbackdroptoandwait,
    looks_switchcostumeto,
    looks_think,
    looks_thinkforsecs,
)

from .operators import (  # noqa: E402  # isort: skip
    operator_add,
    operator_and,
    operator_contains,
    operator_divide,
    operator_equals,
    operator_gt,
    operator_join,
    operator_length,
    operator_letter_of,
    operator_lt,
    operator_mathop,
    operator_mod,
    operator_multiply,
    operator_not,
    operator_or,
    operator_random,
    operator_round,
    operator_subtract,
)

from .data import (  # noqa: E402  # isort: skip
    data_addtolist,
    data_changevariableby,
    data_deletealloflist,
    data_deleteoflist,
    data_hidelist,
    data_hidevariable,
    data_insertatlist,
    data_itemnumoflist,
    data_itemoflist,
    data_lengthoflist,
    data_listcontainsitem,
    data_listcontents,
    data_replaceitemoflist,
    data_setvariableto,
    data_showlist,
    data_showvariable,
    data_variable,
)

from .sensing import (  # noqa: E402  # isort: skip
    sensing_answer,
    sensing_askandwait,
    sensing_coloristouchingcolor,
    sensing_current,
    sensing_dayssince2000,
    sensing_distanceto,
    sensing_keypressed,
    sensing_loud,
    sensing_loudness,
    sensing_mousedown,
    sensing_mousex,
    sensing_mousey,
    sensing_of,
    sensing_online,
    sensing_resettimer,
    sensing_setdragmode,
    sensing_timer,
    sensing_touchingcolor,
    sensing_touchingobject,
    sensing_userid,
    sensing_username,
)

from .sound import (  # noqa: E402  # isort: skip
    sound_changeeffectby,
    sound_changetempo,
    sound_changevolumeby,
    sound_cleareffects,
    sound_play,
    sound_playuntildone,
    sound_seteffectto,
    sound_settempo,
    sound_setvolumeto,
    sound_sounds_menu,
    sound_stopallsounds,
    sound_tempo,
    sound_volume,
)

from .pen import (  # noqa: E402  # isort: skip
    pen_change_pen_size_by,
    pen_clear,
    pen_pen_down,
    pen_pen_up,
    pen_set_pen_color_to_color,
    pen_set_pen_size_to,
    pen_stamp,
)

from .procedures import (  # noqa: E402  # isort: skip
    argument_reporter_boolean,
    argument_reporter_string_number,
    procedures_call,
    procedures_definition,
)

# ═════════════════════════════════════════════════════════════════════════
#  OPCODE_MAP
# ═════════════════════════════════════════════════════════════════════════

OPCODE_MAP: dict[str, Any] = {
    # ── Control ──────────────────────────────────────────────────────
    'control_wait': control_wait,
    'control_repeat': control_repeat,
    'control_forever': control_forever,
    'control_if': control_if,
    'control_if_else': control_if_else,
    'control_wait_until': control_wait_until,
    'control_repeat_until': control_repeat_until,
    'control_while': control_while,
    'control_for_each': control_for_each,
    'control_get_counter': control_get_counter,
    'control_incr_counter': control_incr_counter,
    'control_clear_counter': control_clear_counter,
    'control_create_clone_of': control_create_clone_of,
    'control_delete_this_clone': control_delete_this_clone,
    'control_start_as_clone': control_start_as_clone,
    'control_all_at_once': control_all_at_once,
    'control_stop': control_stop,
    # ── Events ───────────────────────────────────────────────────────
    'event_whenflagclicked': event_whenflagclicked,
    'event_whenbroadcastreceived': event_whenbroadcastreceived,
    'event_whenkeypressed': event_whenkeypressed,
    'event_whenthisspriteclicked': event_whenthisspriteclicked,
    'event_whenstageclicked': event_whenstageclicked,
    'event_whenbackdropswitchesto': event_whenbackdropswitchesto,
    'event_whentouchingobject': event_whentouchingobject,
    'event_whengreaterthan': event_whengreaterthan,
    'event_broadcast': event_broadcast,
    'event_broadcastandwait': event_broadcastandwait,
    # ── Motion ───────────────────────────────────────────────────────
    'motion_movesteps': motion_movesteps,
    'motion_goto': motion_goto,
    'motion_gotoxy': motion_gotoxy,
    'motion_gox': motion_gox,
    'motion_goy': motion_goy,
    'motion_setx': motion_setx,
    'motion_sety': motion_sety,
    'motion_changexby': motion_changexby,
    'motion_changeyby': motion_changeyby,
    'motion_setdirection': motion_setdirection,
    'motion_pointindirection': motion_pointindirection,
    'motion_pointtowards': motion_pointtowards,
    'motion_turnright': motion_turnright,
    'motion_turnleft': motion_turnleft,
    'motion_ifonedgebounce': motion_ifonedgebounce,
    'motion_setrotationstyle': motion_setrotationstyle,
    'motion_xposition': motion_xposition,
    'motion_yposition': motion_yposition,
    'motion_direction': motion_direction,
    'motion_glideto': motion_glideto,
    'motion_glidesecstoxy': motion_glidesecstoxy,
    'motion_glideto_menu': motion_glideto_menu,
    'motion_scroll_right': motion_scroll_right,
    'motion_scroll_up': motion_scroll_up,
    'motion_align_scene': motion_align_scene,
    'motion_xscroll': motion_xscroll,
    'motion_yscroll': motion_yscroll,
    # ── Looks ────────────────────────────────────────────────────────
    'looks_switchcostumeto': looks_switchcostumeto,
    'looks_nextcostume': looks_nextcostume,
    'looks_show': looks_show,
    'looks_hide': looks_hide,
    'looks_gotofront': looks_gotofrontback,
    'looks_gotofrontback': looks_gotofrontback,
    'looks_hideallsprites': looks_hideallsprites,
    'looks_changestretchby': looks_changestretchby,
    'looks_setstretchto': looks_setstretchto,
    'looks_goforwardbackwardlayers': looks_goforwardbackwardlayers,
    'looks_setsizeto': looks_setsizeto,
    'looks_changesizeby': looks_changesizeby,
    'looks_costumenumbername': looks_costumenumbername,
    'looks_costume': looks_costume,
    'looks_backdropnumbername': looks_backdropnumbername,
    'looks_switchbackdropto': looks_switchbackdropto,
    'looks_switchbackdroptoandwait': looks_switchbackdroptoandwait,
    'looks_say': looks_say,
    'looks_sayforsecs': looks_sayforsecs,
    'looks_think': looks_think,
    'looks_thinkforsecs': looks_thinkforsecs,
    'looks_nextbackdrop': looks_nextbackdrop,
    'looks_changeeffectby': looks_changeeffectby,
    'looks_seteffectto': looks_seteffectto,
    'looks_cleargraphiceffects': looks_cleargraphiceffects,
    'looks_size': looks_size,
    # ── Operators ────────────────────────────────────────────────────
    'operator_add': operator_add,
    'operator_subtract': operator_subtract,
    'operator_multiply': operator_multiply,
    'operator_divide': operator_divide,
    'operator_lt': operator_lt,
    'operator_equals': operator_equals,
    'operator_gt': operator_gt,
    'operator_and': operator_and,
    'operator_or': operator_or,
    'operator_not': operator_not,
    'operator_random': operator_random,
    'operator_join': operator_join,
    'operator_letter_of': operator_letter_of,
    'operator_length': operator_length,
    'operator_contains': operator_contains,
    'operator_mod': operator_mod,
    'operator_round': operator_round,
    'operator_mathop': operator_mathop,
    # ── Data — variables ─────────────────────────────────────────────
    'data_setvariableto': data_setvariableto,
    'data_changevariableby': data_changevariableby,
    'data_showvariable': data_showvariable,
    'data_hidevariable': data_hidevariable,
    'data_variable': data_variable,
    # ── Data — lists ─────────────────────────────────────────────────
    'data_addtolist': data_addtolist,
    'data_deleteoflist': data_deleteoflist,
    'data_deletealloflist': data_deletealloflist,
    'data_insertatlist': data_insertatlist,
    'data_replaceitemoflist': data_replaceitemoflist,
    'data_itemoflist': data_itemoflist,
    'data_itemnumoflist': data_itemnumoflist,
    'data_lengthoflist': data_lengthoflist,
    'data_listcontainsitem': data_listcontainsitem,
    'data_listcontents': data_listcontents,
    'data_hidelist': data_hidelist,
    'data_showlist': data_showlist,
    # ── Sensing ──────────────────────────────────────────────────────
    'sensing_touchingobject': sensing_touchingobject,
    'sensing_touchingcolor': sensing_touchingcolor,
    'sensing_coloristouchingcolor': sensing_coloristouchingcolor,
    'sensing_distanceto': sensing_distanceto,
    'sensing_of': sensing_of,
    'sensing_mousex': sensing_mousex,
    'sensing_mousey': sensing_mousey,
    'sensing_setdragmode': sensing_setdragmode,
    'sensing_mousedown': sensing_mousedown,
    'sensing_keypressed': sensing_keypressed,
    'sensing_current': sensing_current,
    'sensing_dayssince2000': sensing_dayssince2000,
    'sensing_loudness': sensing_loudness,
    'sensing_loud': sensing_loud,
    'sensing_askandwait': sensing_askandwait,
    'sensing_answer': sensing_answer,
    'sensing_resettimer': sensing_resettimer,
    'sensing_timer': sensing_timer,
    'sensing_online': sensing_online,
    'sensing_username': sensing_username,
    'sensing_userid': sensing_userid,
    # ── Sound ────────────────────────────────────────────────────────
    'sound_sounds_menu': sound_sounds_menu,
    'sound_play': sound_play,
    'sound_playuntildone': sound_playuntildone,
    'sound_stopallsounds': sound_stopallsounds,
    'sound_setvolumeto': sound_setvolumeto,
    'sound_changevolumeby': sound_changevolumeby,
    'sound_volume': sound_volume,
    'sound_seteffectto': sound_seteffectto,
    'sound_changeeffectby': sound_changeeffectby,
    'sound_cleareffects': sound_cleareffects,
    'sound_settempo': sound_settempo,
    'sound_changetempo': sound_changetempo,
    'sound_tempo': sound_tempo,
    # ── Pen ──────────────────────────────────────────────────────────
    'pen_penDown': pen_pen_down,
    'pen_penUp': pen_pen_up,
    'pen_setPenColorToColor': pen_set_pen_color_to_color,
    'pen_changePenSizeBy': pen_change_pen_size_by,
    'pen_setPenSizeTo': pen_set_pen_size_to,
    'pen_clear': pen_clear,
    'pen_stamp': pen_stamp,
    # ── Procedures ───────────────────────────────────────────────────
    'procedures_def': procedures_definition,
    'procedures_definition': procedures_definition,
    'procedures_call': procedures_call,
    'argument_reporter_string_number': argument_reporter_string_number,
    'argument_reporter_boolean': argument_reporter_boolean,
    'procedures_prototype': procedures_definition,
    'looks_backdrops': looks_backdrops,
}

# Re-export for convenience
__all__ += [
    'control_wait',
    'control_repeat',
    'control_forever',
    'control_if',
    'control_if_else',
    'control_wait_until',
    'control_repeat_until',
    'control_while',
    'control_for_each',
    'control_get_counter',
    'control_incr_counter',
    'control_clear_counter',
    'control_create_clone_of',
    'control_delete_this_clone',
    'control_start_as_clone',
    'control_all_at_once',
    'control_stop',
    'event_whenflagclicked',
    'event_whenbroadcastreceived',
    'event_whenkeypressed',
    'event_whenthisspriteclicked',
    'event_whenstageclicked',
    'event_whenbackdropswitchesto',
    'event_whentouchingobject',
    'event_whengreaterthan',
    'event_broadcast',
    'event_broadcastandwait',
    'motion_movesteps',
    'motion_goto',
    'motion_gotoxy',
    'motion_gox',
    'motion_goy',
    'motion_setx',
    'motion_sety',
    'motion_changexby',
    'motion_changeyby',
    'motion_setdirection',
    'motion_pointindirection',
    'motion_pointtowards',
    'motion_turnright',
    'motion_turnleft',
    'motion_ifonedgebounce',
    'motion_setrotationstyle',
    'motion_xposition',
    'motion_yposition',
    'motion_direction',
    'motion_glideto',
    'motion_glidesecstoxy',
    'motion_glideto_menu',
    'motion_scroll_right',
    'motion_scroll_up',
    'motion_align_scene',
    'motion_xscroll',
    'motion_yscroll',
    'looks_switchcostumeto',
    'looks_nextcostume',
    'looks_show',
    'looks_hide',
    'looks_gotofrontback',
    'looks_hideallsprites',
    'looks_changestretchby',
    'looks_setstretchto',
    'looks_goforwardbackwardlayers',
    'looks_setsizeto',
    'looks_changesizeby',
    'looks_costumenumbername',
    'looks_costume',
    'looks_backdropnumbername',
    'looks_switchbackdropto',
    'looks_switchbackdroptoandwait',
    'looks_say',
    'looks_sayforsecs',
    'looks_think',
    'looks_thinkforsecs',
    'looks_nextbackdrop',
    'looks_changeeffectby',
    'looks_seteffectto',
    'looks_cleargraphiceffects',
    'looks_size',
    'operator_add',
    'operator_subtract',
    'operator_multiply',
    'operator_divide',
    'operator_lt',
    'operator_equals',
    'operator_gt',
    'operator_and',
    'operator_or',
    'operator_not',
    'operator_random',
    'operator_join',
    'operator_letter_of',
    'operator_length',
    'operator_contains',
    'operator_mod',
    'operator_round',
    'operator_mathop',
    'data_setvariableto',
    'data_changevariableby',
    'data_showvariable',
    'data_hidevariable',
    'data_variable',
    'data_addtolist',
    'data_deleteoflist',
    'data_deletealloflist',
    'data_insertatlist',
    'data_replaceitemoflist',
    'data_itemoflist',
    'data_itemnumoflist',
    'data_lengthoflist',
    'data_listcontainsitem',
    'data_listcontents',
    'data_hidelist',
    'data_showlist',
    'sensing_touchingobject',
    'sensing_touchingcolor',
    'sensing_coloristouchingcolor',
    'sensing_distanceto',
    'sensing_of',
    'sensing_mousex',
    'sensing_mousey',
    'sensing_setdragmode',
    'sensing_mousedown',
    'sensing_keypressed',
    'sensing_current',
    'sensing_dayssince2000',
    'sensing_loudness',
    'sensing_loud',
    'sensing_askandwait',
    'sensing_answer',
    'sensing_resettimer',
    'sensing_timer',
    'sensing_online',
    'sensing_username',
    'sensing_userid',
    'sound_sounds_menu',
    'sound_play',
    'sound_playuntildone',
    'sound_stopallsounds',
    'sound_setvolumeto',
    'sound_changevolumeby',
    'sound_volume',
    'sound_seteffectto',
    'sound_changeeffectby',
    'sound_cleareffects',
    'sound_settempo',
    'sound_changetempo',
    'sound_tempo',
    'pen_pen_down',
    'pen_pen_up',
    'pen_set_pen_color_to_color',
    'pen_change_pen_size_by',
    'pen_set_pen_size_to',
    'pen_clear',
    'pen_stamp',
    'procedures_definition',
    'procedures_call',
    'argument_reporter_string_number',
    'argument_reporter_boolean',
]
