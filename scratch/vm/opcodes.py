"""
Opcodes — the actual block implementations for the Scratch VM.

Each handler is a generator function ``(runtime, target, block) -> Generator``.
* Stack blocks end normally (``StopIteration``) when done.
* Reporter blocks ``yield Report(value)``.
* Blocks that need to pause ``yield YIELD`` or ``yield Wait(secs)``.
"""

from __future__ import annotations

import math
import pygame
import random
import time
import json
from collections.abc import Generator
from typing import Any

from .runtime import Handler, Runtime
from .target import Target
from .thread import Report, Thread, ThreadStatus, Wait, YIELD
from .types import Block, Input, Sound
from .constants import (
    BOUNCE_REFLECT_ANGLE,
    BUBBLE_DECIMAL_THRESHOLD,
    BUBBLE_MAX_CHARS,
    DEFAULT_TEMPO_BPM,
    DISTANCE_UNREACHABLE,
    DST_OFFSET_SECS,
    LIST_INDEX_ALL,
    LIST_INDEX_ALL_SENTINEL,
    LIST_INDEX_ANY,
    LIST_INDEX_LAST,
    LIST_INDEX_RANDOM,
    LOOKS_NEXTCOSTUME_OFFSET,
    MATH_TRIG_PRECISION,
    PAN_MAX,
    PAN_MIN,
    PEN_SIZE_MIN,
    PITCH_MAX,
    PITCH_MIN,
    ROTATION_ALL_AROUND,
    ROTATION_DONT_ROTATE,
    ROTATION_LEFT_RIGHT,
    SCRATCH_RIGHT,
    SECONDS_PER_DAY,
    SOUND_EFFECT_PAN,
    SOUND_EFFECT_PITCH,
    STAGE_BOTTOM,
    STAGE_LEFT,
    STAGE_RIGHT,
    STAGE_TOP,
    STOP_ALL,
    STOP_OTHER_IN_SPRITE,
    STOP_OTHER_IN_STAGE,
    STOP_THIS_SCRIPT,
    TEMPO_MAX,
    TEMPO_MIN,
    VOLUME_MAX,
    VOLUME_MIN,
    YEAR_2000_EPOCH,
)


# ── Helpers ──────────────────────────────────────────────────────────────


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
    - If either converts to NaN (or is None / whitespace), compare case-insensitively as strings.
    - Infinity special-cases handled.
    """
    # None or whitespace-only strings → treat as NaN (scratch-vm Cast.isWhiteSpace)
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

    # Both are numbers — special-case Infinity comparisons
    if n1 == float('inf') and n2 == float('inf'):
        return 0
    if n1 == float('-inf') and n2 == float('-inf'):
        return 0

    if n1 < n2:
        return -1
    if n1 > n2:
        return 1
    return 0


# ═══════════════════════════════════════════════════════════════════════
#  CONTROL
# ═══════════════════════════════════════════════════════════════════════


def control_wait(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    dur = rt.num(tgt, block, 'DURATION')
    yield Wait(dur)


def control_repeat(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    count = rt.num_int(tgt, block, 'TIMES')
    sub_id = _substack_val(block.inputs.get('SUBSTACK'))
    for _ in range(count):
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
        yield YIELD


def control_forever(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    sub_id = _substack_val(block.inputs.get('SUBSTACK'))
    while True:
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
        yield YIELD


def control_if(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    cond = rt.truthy(tgt, block, 'CONDITION')
    sub_id = _substack_val(block.inputs.get('SUBSTACK'))
    if cond and sub_id:
        yield from rt.execute_substack(tgt, sub_id)


def control_if_else(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    cond = rt.truthy(tgt, block, 'CONDITION')
    if cond:
        sub_id = _substack_val(block.inputs.get('SUBSTACK'))
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
    else:
        sub_id = _substack_val(block.inputs.get('SUBSTACK2'))
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)


def control_wait_until(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    while not rt.truthy(tgt, block, 'CONDITION'):
        yield YIELD


def control_repeat_until(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    substack = block.inputs.get('SUBSTACK')
    while not rt.truthy(tgt, block, 'CONDITION'):
        if substack and substack.value:
            yield from rt.execute_substack(tgt, substack.value)
        yield YIELD


def control_stop(rt: Runtime, tgt: Target, block: Block) -> None:
    """Stop behaviour: stop all | this script | other scripts in sprite | other scripts in stage."""
    option = block.fields.get('STOP_OPTION')
    choice = option.value if option else STOP_ALL
    _cur = rt.current_thread
    if choice == STOP_ALL:
        for th in list(rt.threads):
            th.status = ThreadStatus.DONE
    elif choice == STOP_THIS_SCRIPT:
        if _cur is not None:
            _cur.status = ThreadStatus.DONE
    elif choice == STOP_OTHER_IN_SPRITE:
        for th in list(rt.threads):
            if th.target is tgt and th is not _cur:
                th.status = ThreadStatus.DONE
    elif choice == STOP_OTHER_IN_STAGE:
        for th in list(rt.threads):
            if th.target.is_stage and th is not _cur:
                th.status = ThreadStatus.DONE


def control_while(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    substack = block.inputs.get('SUBSTACK')
    while rt.truthy(tgt, block, 'CONDITION'):
        if substack and substack.value:
            yield from rt.execute_substack(tgt, substack.value)
        yield YIELD


def control_for_each(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    var_field = block.fields.get('VARIABLE')
    var_name = _field_val(var_field) if var_field else ''
    var = tgt.lookup_variable(var_name) if var_name else None
    if var is None:
        return
    from_val = rt.num_int(tgt, block, 'FROM')
    to_val = rt.num_int(tgt, block, 'TO')
    step = 1 if from_val <= to_val else -1
    for i in range(from_val, to_val + step, step):
        var.value = i
        sub_id = _substack_val(block.inputs.get('SUBSTACK'))
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
        yield YIELD


def control_get_counter(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(rt._for_each_counter)


def control_incr_counter(rt: Runtime, tgt: Target, block: Block) -> None:
    rt._for_each_counter += 1


def control_clear_counter(rt: Runtime, tgt: Target, block: Block) -> None:
    rt._for_each_counter = 0


# ═══════════════════════════════════════════════════════════════════════
def control_create_clone_of(rt: Runtime, tgt: Target, block: Block) -> None:
    """Create a clone of the named sprite."""
    clone_opt = block.fields.get('CLONE_OPTION')
    name = _field_val(clone_opt) if clone_opt else ''
    if not name:
        name = _str(rt.val(tgt, block, 'CLONE_OPTION'))
    if name == '_myself_':
        name = tgt.name
    rt.clone_target(name)


def control_delete_this_clone(rt: Runtime, tgt: Target, block: Block) -> None:
    """Delete the current sprite clone."""
    rt.remove_clone(tgt)


def control_start_as_clone(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — fires when a clone is created. Threads started by clone_target."""


def control_all_at_once(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Run the substack without yielding between blocks (all at once)."""
    sub_id = _substack_val(block.inputs.get('SUBSTACK'))
    if sub_id:
        yield from rt.execute_substack(tgt, sub_id, yield_between=False)


# ═══════════════════════════════════════════════════════════════════════
#  CONTROL
# ═══════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
#  EVENT
# ═══════════════════════════════════════════════════════════════════════


def event_whenflagclicked(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — the scheduler starts the next block directly."""
    pass


def event_whenbroadcastreceived(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by broadcast."""
    pass


def event_whenkeypressed(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by key press. Threads started by ``start_key_hat``."""
    pass


def event_whenthisspriteclicked(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by sprite click."""
    pass


def event_whenstageclicked(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by stage click."""
    pass


def event_whenbackdropswitchesto(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by backdrop switch."""
    pass


def event_whentouchingobject(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Edge-activated hat — returns True when touching the specified object."""
    obj = block.fields.get('TOUCHINGOBJECTMENU')
    obj_name = _field_val(obj) if obj else ''
    if obj_name == '':
        yield Report(False)
        return
    touching = _touching_object_check(rt, tgt, obj_name)
    yield Report(rt._check_edge_hat('event_whentouchingobject', tgt, block, touching))

def event_whengreaterthan(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Edge-activated hat — returns True when timer/loudness > VALUE."""
    option = block.fields.get('WHENGREATERTHANMENU')
    opt = _field_val(option) if option else ''
    value = rt.num(tgt, block, 'VALUE')
    if opt == 'timer':
        result = rt.clock.now() > value
    elif opt == 'loudness':
        result = False  # no microphone
    else:
        result = False
    yield Report(rt._check_edge_hat('event_whengreaterthan', tgt, block, result))


def event_broadcast(rt: Runtime, tgt: Target, block: Block) -> None:
    rt.broadcast(rt.val(tgt, block, 'BROADCAST_INPUT'))


def event_broadcastandwait(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    started = rt.broadcast(rt.val(tgt, block, 'BROADCAST_INPUT'))
    # Yield until all started threads are done
    while any(th for th in started if not th.is_done()):
        yield YIELD


# ═══════════════════════════════════════════════════════════════════════
#  MOTION
# ═══════════════════════════════════════════════════════════════════════


def motion_movesteps(rt: Runtime, tgt: Target, block: Block) -> None:
    steps = rt.num(tgt, block, 'STEPS')
    rad = math.radians(SCRATCH_RIGHT - tgt.direction)
    tgt.set_xy(tgt.x + steps * math.cos(rad), tgt.y + steps * math.sin(rad))


def _target_xy(rt: Runtime, target_name: str) -> tuple[float, float] | None:
    """Resolve a target name to (x, y) for go-to / point-towards."""
    if target_name == '_mouse_':
        return (rt._mouse_x, rt._mouse_y)
    if target_name == '_random_':
        return (round(random.uniform(STAGE_LEFT, STAGE_RIGHT)), round(random.uniform(STAGE_BOTTOM, STAGE_TOP)))
    t = rt.get_target_by_name(target_name)
    if t is not None:
        return (t.x, t.y)
    return None


def motion_goto(rt: Runtime, tgt: Target, block: Block) -> None:
    target_name = _str(block.fields.get('TO'))
    xy = _target_xy(rt, target_name)
    if xy is not None:
        tgt.set_xy(xy[0], xy[1])


def motion_gotoxy(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.set_xy(
        rt.num(tgt, block, 'X'), rt.num(tgt, block, 'Y')
    )


def motion_gox(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.x = rt.num(tgt, block, 'X')


def motion_goy(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.y = rt.num(tgt, block, 'Y')


def motion_setx(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.x = rt.num(tgt, block, 'X')


def motion_sety(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.y = rt.num(tgt, block, 'Y')


def motion_changexby(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.x = tgt.x + rt.num(tgt, block, 'DX')


def motion_changeyby(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.y = tgt.y + rt.num(tgt, block, 'DY')


def motion_setdirection(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.direction = rt.num(tgt, block, 'DIRECTION')


def motion_pointindirection(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.direction = rt.num(tgt, block, 'DIRECTION')


def motion_pointtowards(rt: Runtime, tgt: Target, block: Block) -> None:
    target_name = _str(block.fields.get('TOWARDS'))
    xy = _target_xy(rt, target_name)
    if xy is None:
        return
    dx = xy[0] - tgt.x
    dy = xy[1] - tgt.y
    direction = SCRATCH_RIGHT - math.degrees(math.atan2(dy, dx))
    tgt.direction = direction

def motion_turnright(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.direction += rt.num(tgt, block, 'DEGREES')


def motion_turnleft(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.direction -= rt.num(tgt, block, 'DEGREES')

def motion_ifonedgebounce(rt: Runtime, tgt: Target, block: Block) -> None:
    if not tgt.costume or tgt.costume.surface is None:
        return
    surf = tgt.costume.surface
    w, h = surf.get_width(), surf.get_height()
    left = STAGE_LEFT + w / 2
    right = STAGE_RIGHT - w / 2
    top = STAGE_TOP - h / 2
    bottom = STAGE_BOTTOM + h / 2
    bounced = False
    if tgt.x > right:
        tgt.x = right
        bounced = True
    elif tgt.x < left:
        tgt.x = left
        bounced = True
    if tgt.y > top:
        tgt.y = top
        bounced = True
    elif tgt.y < bottom:
        tgt.y = bottom
        bounced = True
    if bounced:
        tgt.direction = BOUNCE_REFLECT_ANGLE - tgt.direction
    # keepInFence: clamp position to fence bounds unconditionally
    if tgt.x < left:
        tgt.x = left
    elif tgt.x > right:
        tgt.x = right
    if tgt.y < bottom:
        tgt.y = bottom
    elif tgt.y > top:
        tgt.y = top


def motion_setrotationstyle(rt: Runtime, tgt: Target, block: Block) -> None:
    style = block.fields.get('STYLE')
    if style:
        tgt.rotation_style = style.value


def motion_xposition(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    val = tgt.x
    if abs(val - round(val)) < 1e-9:
        val = round(val)
    yield Report(val)


def motion_yposition(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    val = tgt.y
    if abs(val - round(val)) < 1e-9:
        val = round(val)
    yield Report(val)


def motion_direction(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(tgt.direction)


def motion_glidesecstoxy(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    secs = rt.num(tgt, block, 'SECS')
    x = rt.num(tgt, block, 'X')
    y = rt.num(tgt, block, 'Y')
    if secs <= 0:
        tgt.set_xy(x, y)
        return
    start_x, start_y = tgt.x, tgt.y
    frames = rt.clock.frames_for(secs)
    frame = 0
    while frame < frames:
        frac = frame / frames
        tgt.set_xy(start_x + frac * (x - start_x), start_y + frac * (y - start_y))
        frame += 1
        yield YIELD
    tgt.set_xy(x, y)


def motion_glideto(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    secs = rt.num(tgt, block, 'SECS')
    target_name = _str(block.fields.get('TO'))
    xy = _target_xy(rt, target_name)
    if xy is None:
        return
    x, y = xy
    if secs <= 0:
        tgt.set_xy(x, y)
        return
    start_x, start_y = tgt.x, tgt.y
    frames = rt.clock.frames_for(secs)
    frame = 0
    while frame < frames:
        frac = frame / frames
        tgt.set_xy(start_x + frac * (x - start_x), start_y + frac * (y - start_y))
        frame += 1
        yield YIELD
    tgt.set_xy(x, y)


def motion_glideto_menu(rt: Runtime, tgt: Target, block: Block) -> None:
    pass


# Legacy no-op motion blocks (do nothing, for compatibility)
def motion_scroll_right(rt: Runtime, tgt: Target, block: Block) -> None:
    pass


def motion_scroll_up(rt: Runtime, tgt: Target, block: Block) -> None:
    pass


def motion_align_scene(rt: Runtime, tgt: Target, block: Block) -> None:
    pass


def motion_xscroll(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(0)


def motion_yscroll(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(0)


# ═══════════════════════════════════════════════════════════════════════
#  LOOKS
# ═══════════════════════════════════════════════════════════════════════


def _set_costume(tgt: Target, requested: Any) -> None:
    """Scratch-compatible costume/backdrop selection.

    Mirrors official ``_setCostume``:
    - Numbers → 1-based index (always)
    - Strings → try name match, then 'next costume'/'previous costume', then number parse
    - NaN/Infinity/True → first costume
    - False/0 → last costume
    - Whitespace → no-op
    - Negative wrap, over-large wrap.
    """

    n = len(tgt.costumes)
    if n == 0:
        return
    if isinstance(requested, bool):
        # True → first, False → last
        idx = 0 if requested else n - 1
        tgt.costume_index = idx
        return
    if isinstance(requested, (int, float)):
        # Numbers → treat as 1-based index
        if math.isnan(requested) or math.isinf(requested):
            idx = 0
        else:
            idx = int(requested) - 1
        idx %= n
        tgt.costume_index = idx
        return
    # String
    s = _str(requested)
    if s.strip() == '':
        return  # whitespace → no-op
    # Try name match first
    for i, c in enumerate(tgt.costumes):
        if c.name == s:
            tgt.costume_index = i
            return
    if s == 'next costume':
        return
    if s == 'previous costume':
        return
    # Try numeric parse
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


def looks_switchcostumeto(rt: Runtime, tgt: Target, block: Block) -> None:

    val = rt.val(tgt, block, 'COSTUME')
    _set_costume(tgt, val)


def looks_nextcostume(rt: Runtime, tgt: Target, block: Block) -> None:
    _set_costume(tgt, tgt.costume_index + LOOKS_NEXTCOSTUME_OFFSET)


def looks_show(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.visible = True


def looks_hide(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.visible = False


def looks_gotofrontback(rt: Runtime, tgt: Target, block: Block) -> None:
    """Go to front or back layer."""
    if tgt.is_stage:
        return
    fb = block.fields.get('FRONT_BACK')
    choice = _field_val(fb) if fb else 'front'
    if choice == 'front':
        max_layer = max((o.layer_order for o in rt.sprite_targets()), default=0)
        tgt.layer_order = max_layer + 1
    else:
        min_layer = min((o.layer_order for o in rt.sprite_targets()), default=0)
        tgt.layer_order = min_layer - 1


def looks_hideallsprites(rt: Runtime, tgt: Target, block: Block) -> None:
    """Legacy no-op."""
    pass


def looks_changestretchby(rt: Runtime, tgt: Target, block: Block) -> None:
    """Legacy no-op."""
    pass


def looks_setstretchto(rt: Runtime, tgt: Target, block: Block) -> None:
    """Legacy no-op."""
    pass


def looks_goforwardbackwardlayers(rt: Runtime, tgt: Target, block: Block) -> None:
    if tgt.is_stage:
        return
    num = rt.num_int(tgt, block, 'NUM')
    direction = block.fields.get('FORWARD_BACKWARD')
    if direction and direction.value == 'backward':
        num = -num
    tgt.layer_order += num

def looks_setsizeto(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.size = rt.num(tgt, block, 'SIZE')


def looks_changesizeby(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.size += rt.num(tgt, block, 'CHANGE')


def looks_costumenumbername(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    numname = block.fields.get('NUMBER_NAME')
    if numname and numname.value == 'number':
        yield Report(tgt.costume_index + 1)
    else:
        yield Report(tgt.current_costume_name)

def looks_costume(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Menu block: costume dropdown for ``looks_switchcostumeto``.
    Returns the selected costume name from the ``COSTUME`` field.
    """
    name = _field_val(block.fields.get('COSTUME'))
    yield Report(name)



def looks_backdrops(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Menu block: backdrop dropdown for ``looks_switchbackdropto``.
    Returns the selected backdrop name from the ``BACKDROP`` field.
    """
    name = _field_val(block.fields.get('BACKDROP'))
    yield Report(name)


def looks_backdropnumbername(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    numname = block.fields.get('NUMBER_NAME')
    if numname and numname.value == 'number':
        yield Report(tgt.costume_index + 1)
    else:
        yield Report(tgt.current_costume_name)

    yield Report(tgt.current_costume_name)


def _set_backdrop(rt: Runtime, val: Any) -> list[Thread]:
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
    # Try name match
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
            # Fall through to _set_costume for number/other string parsing
            _set_costume(stage, val)
    if stage.costume_index != old_idx:
        return rt.start_hat('event_whenbackdropswitchesto')
    return []
    
    
def looks_switchbackdropto(rt: Runtime, tgt: Target, block: Block) -> None:
    """Switch backdrop (on the stage, not the sprite)."""
    if rt.stage is None:
        return
    val = rt.val(tgt, block, 'BACKDROP')
    _set_backdrop(rt, val)
    
    
def looks_switchbackdroptoandwait(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Switch backdrop and wait for all ``event_whenbackdropswitchesto`` handlers to finish."""
    if rt.stage is None:
        return
    val = rt.val(tgt, block, 'BACKDROP')
    started = _set_backdrop(rt, val)
    while any(th for th in started if th.status != 'done' and th in rt.threads):
        yield YIELD


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


def looks_say(rt: Runtime, tgt: Target, block: Block) -> None:
    msg = rt.val(tgt, block, 'MESSAGE')
    tgt.say_text = _format_bubble_text(msg) or None


def looks_sayforsecs(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    msg = rt.val(tgt, block, 'MESSAGE')
    secs = rt.num(tgt, block, 'SECS')
    tgt.say_text = _format_bubble_text(msg) or None
    if secs > 0:
        tgt.say_until = rt.clock._tick + rt.clock.frames_for(secs)
        yield Wait(secs)
    tgt.say_text = None
    tgt.say_until = None


def looks_think(rt: Runtime, tgt: Target, block: Block) -> None:
    """Think bubble."""
    msg = rt.val(tgt, block, 'MESSAGE')
    tgt.say_text = _format_bubble_text(msg) or None


def looks_thinkforsecs(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Think bubble for a duration."""
    msg = rt.val(tgt, block, 'MESSAGE')
    secs = rt.num(tgt, block, 'SECS')
    tgt.say_text = _format_bubble_text(msg) or None
    if secs > 0:
        tgt.say_until = rt.clock._tick + rt.clock.frames_for(secs)
        yield Wait(secs)
    tgt.say_text = None
    tgt.say_until = None


def looks_nextbackdrop(rt: Runtime, tgt: Target, block: Block) -> None:
    """Switch to next backdrop on stage."""
    if rt.stage:
        n = len(rt.stage.costumes)
        if n > 0:
            rt.stage.costume_index = (rt.stage.costume_index + 1) % n
    
    
def looks_changeeffectby(rt: Runtime, tgt: Target, block: Block) -> None:
    effect = _field_val(block.fields.get('EFFECT')) if block.fields.get('EFFECT') else ''
    change = rt.num(tgt, block, 'CHANGE')
    if effect:
        val = tgt.effects.get(effect, 0) + change
        if effect == 'ghost':
            val = max(0, min(100, val))
        elif effect == 'brightness':
            val = max(-100, min(100, val))
        tgt.effects[effect] = val


def looks_seteffectto(rt: Runtime, tgt: Target, block: Block) -> None:
    effect = _field_val(block.fields.get('EFFECT')) if block.fields.get('EFFECT') else ''
    value = rt.num(tgt, block, 'VALUE')
    if effect:
        if effect == 'ghost':
            value = max(0, min(100, value))
        elif effect == 'brightness':
            value = max(-100, min(100, value))
        tgt.effects[effect] = value


def looks_cleargraphiceffects(rt: Runtime, tgt: Target, block: Block) -> None:
    for k in tgt.effects:
        tgt.effects[k] = 0


def looks_size(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Reporter: current sprite size."""
    yield Report(tgt.size)


# ═══════════════════════════════════════════════════════════════════════
#  OPERATORS
# ═══════════════════════════════════════════════════════════════════════


def operator_add(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.num(tgt, block, 'NUM1')
    b = rt.num(tgt, block, 'NUM2')
    yield Report(a + b)


def operator_subtract(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.num(tgt, block, 'NUM1')
    b = rt.num(tgt, block, 'NUM2')
    yield Report(a - b)


def operator_multiply(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.num(tgt, block, 'NUM1')
    b = rt.num(tgt, block, 'NUM2')
    yield Report(a * b)


def operator_divide(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.num(tgt, block, 'NUM1')
    b = rt.num(tgt, block, 'NUM2')
    # _num handles Infinity/INFINITY distinction already
    yield Report(a / b if b != 0 else float('inf'))


def operator_lt(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.val(tgt, block, 'OPERAND1')
    b = rt.val(tgt, block, 'OPERAND2')
    yield Report(_scratch_compare(a, b) < 0)


def operator_equals(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.val(tgt, block, 'OPERAND1')
    b = rt.val(tgt, block, 'OPERAND2')
    yield Report(_scratch_compare(a, b) == 0)


def operator_gt(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.val(tgt, block, 'OPERAND1')
    b = rt.val(tgt, block, 'OPERAND2')
    yield Report(_scratch_compare(a, b) > 0)


def operator_and(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.truthy(tgt, block, 'OPERAND1')
    b = rt.truthy(tgt, block, 'OPERAND2')
    yield Report(a and b)


def operator_or(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.truthy(tgt, block, 'OPERAND1')
    b = rt.truthy(tgt, block, 'OPERAND2')
    yield Report(a or b)


def operator_not(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.truthy(tgt, block, 'OPERAND')
    yield Report(not a)


def operator_random(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    lo = rt.num(tgt, block, 'FROM')
    hi = rt.num(tgt, block, 'TO')
    if lo > hi:
        lo, hi = hi, lo
    lo_int, hi_int = int(lo), int(hi)
    if lo == lo_int and hi == hi_int:
        yield Report(random.randint(lo_int, hi_int))
    else:
        yield Report(lo + (hi - lo) * random.random())


def operator_join(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = _str(rt.val(tgt, block, 'STRING1'))
    b = _str(rt.val(tgt, block, 'STRING2'))
    yield Report(a + b)


def operator_letter_of(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    idx = rt.num_int(tgt, block, 'LETTER')
    s = _str(rt.val(tgt, block, 'STRING'))
    if 1 <= idx <= len(s):
        yield Report(s[idx - 1])
    yield Report('')


def operator_length(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    s = _str(rt.val(tgt, block, 'STRING'))
    yield Report(len(s))


def operator_contains(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    s1 = _str(rt.val(tgt, block, 'STRING1'))
    s2 = _str(rt.val(tgt, block, 'STRING2'))
    # Scratch comparison: case-insensitive
    yield Report(s2.lower() in s1.lower())


def operator_mod(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.num(tgt, block, 'NUM1')
    b = rt.num(tgt, block, 'NUM2')
    yield Report(a % b if b != 0 else float('nan'))


def operator_round(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    n = rt.num(tgt, block, 'NUM')
    yield Report(round(n))


def operator_mathop(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    op = block.fields.get('OPERATOR')
    n = rt.num(tgt, block, 'NUM')
    if op is None:
        yield Report(0)
        return
    match _field_val(op):
        case 'abs':
            r = abs(n)
        case 'floor':
            r = math.floor(n)
        case 'ceiling':
            r = math.ceil(n)
        case 'sqrt':
            r = math.sqrt(n) if n >= 0 else float('nan')
        case 'sin':
            r = round(math.sin(math.radians(n)), MATH_TRIG_PRECISION)
        case 'cos':
            r = round(math.cos(math.radians(n)), MATH_TRIG_PRECISION)
        case 'tan':
            r = math.tan(math.radians(n)) if n % 180 != 90 else float('inf')
        case 'asin':
            r = math.degrees(math.asin(max(-1, min(1, n))))
        case 'acos':
            r = math.degrees(math.acos(max(-1, min(1, n))))
        case 'atan':
            r = math.degrees(math.atan(n))
        case 'ln':
            r = math.log(n) if n > 0 else float('-inf')
        case 'log':
            r = math.log10(n) if n > 0 else float('-inf')
        case 'e ^':
            r = math.exp(n)
        case '10 ^':
            r = math.pow(10, n)
        case _:
            r = 0
    yield Report(r)


# ═══════════════════════════════════════════════════════════════════════
#  DATA — Variables
# ═══════════════════════════════════════════════════════════════════════


def data_setvariableto(rt: Runtime, tgt: Target, block: Block) -> None:
    var_name = _field_val(block.fields.get('VARIABLE'))
    value = rt.val(tgt, block, 'VALUE')
    if var_name:
        var = tgt.lookup_variable(var_name)
        if var is None and rt.stage:
            var = rt.stage.lookup_variable(var_name)
        if var:
            var.value = value


def data_changevariableby(rt: Runtime, tgt: Target, block: Block) -> None:
    var_name = _field_val(block.fields.get('VARIABLE'))
    delta = rt.num(tgt, block, 'VALUE')
    if var_name:
        var = tgt.lookup_variable(var_name)
        if var is None and rt.stage:
            var = rt.stage.lookup_variable(var_name)
        if var:
            var.value = _num(var.value) + delta


def data_showvariable(rt: Runtime, tgt: Target, block: Block) -> None:
    """Toggle variable monitor visibility — no-op for now."""
    pass


def data_hidevariable(rt: Runtime, tgt: Target, block: Block) -> None:
    pass


def data_variable(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    var_name = _field_val(block.fields.get('VARIABLE'))
    if var_name:
        var = tgt.lookup_variable(var_name)
        if var is None and rt.stage:
            var = rt.stage.lookup_variable(var_name)
        if var:
            yield Report(var.value)
    yield Report(0)


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
# ═══════════════════════════════════════════════════════════════════════
#  DATA — Lists
# ═══════════════════════════════════════════════════════════════════════


def data_addtolist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.val(tgt, block, 'ITEM')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst and len(lst.contents) < LIST_ITEM_LIMIT:
            lst.contents.append(item)


def data_deleteoflist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    value = rt.val(tgt, block, 'INDEX')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            idx = _to_list_index(value, len(lst.contents))
            if idx == 'ALL':
                lst.contents.clear()
            elif isinstance(idx, int):
                del lst.contents[idx - 1]


def data_insertatlist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.val(tgt, block, 'ITEM')
    idx_val = rt.val(tgt, block, 'INDEX')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            length = len(lst.contents)
            # Pop last if at limit before inserting
            if length >= LIST_ITEM_LIMIT:
                lst.contents.pop()
                length = len(lst.contents)
            # Determine 0-based insertion position
            if isinstance(idx_val, str):
                v = idx_val.lower()
                if v == LIST_INDEX_LAST:
                    pos = length  # insert at end
                elif v in (LIST_INDEX_RANDOM, LIST_INDEX_ANY):
                    pos = random.randint(0, length)
                else:
                    idx = _to_list_index(idx_val, length)
                    if isinstance(idx, int):
                        pos = min(idx - 1, length)
                    else:
                        return
            else:
                idx = _to_list_index(idx_val, length)
                if isinstance(idx, int):
                    pos = min(idx - 1, length)
                else:
                    return
            lst.contents.insert(max(0, pos), item)


def data_replaceitemoflist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.val(tgt, block, 'ITEM')
    value = rt.val(tgt, block, 'INDEX')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            idx = _to_list_index(value, len(lst.contents))
            if isinstance(idx, int):
                lst.contents[idx - 1] = item


def data_deletealloflist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            lst.contents.clear()


def data_itemoflist(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    list_name = _field_val(block.fields.get('LIST'))
    value = rt.val(tgt, block, 'INDEX')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            idx = _to_list_index(value, len(lst.contents))
            if isinstance(idx, int):
                yield Report(lst.contents[idx - 1])
    yield Report('')


def data_lengthoflist(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    list_name = _field_val(block.fields.get('LIST'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            yield Report(len(lst.contents))
    yield Report(0)


def data_listcontainsitem(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.val(tgt, block, 'ITEM')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            # Scratch comparison: case-insensitive, type-insensitive
            yield Report(any(_scratch_compare(item, x) == 0 for x in lst.contents))
    yield Report(False)


def data_itemnumoflist(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.val(tgt, block, 'ITEM')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            for i, x in enumerate(lst.contents, 1):
                if _scratch_compare(item, x) == 0:
                    yield Report(i)
    yield Report(0)


def data_listcontents(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Reporter: return list contents as a space-separated string."""
    list_name = _field_val(block.fields.get('LIST'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            items = lst.contents
            if all(len(str(x)) == 1 for x in items):
                yield Report(''.join(str(x) for x in items))
            else:
                yield Report(' '.join(str(x) for x in items))
    yield Report('')


def data_hidelist(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hide list monitor — no-op."""
    pass


def data_showlist(rt: Runtime, tgt: Target, block: Block) -> None:
    """Show list monitor — no-op."""
    pass


# ═══════════════════════════════════════════════════════════════════════
#  SENSING
# ═══════════════════════════════════════════════════════════════════════


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

def sensing_touchingobject(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    obj = block.fields.get('TOUCHINGOBJECTMENU')
    if obj is None:
        obj_input = block.inputs.get('TOUCHINGOBJECTMENU')
        if obj_input is not None:
            if isinstance(obj_input, Input):
                obj_name = _str(rt.resolve_input(tgt, obj_input.value))
            else:
                obj_name = _str(rt.resolve_input(tgt, obj_input))
        else:
            obj_name = '_mouse_'
    else:
        obj_name = _field_val(obj)
    yield Report(_touching_object_check(rt, tgt, obj_name))


def sensing_touchingcolor(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(False)  # simplified


def sensing_keypressed(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    key_name = _field_val(block.fields.get('KEY_OPTION'))
    if not hasattr(rt, '_keyboard'):
        yield Report(False)
        return
    if key_name == 'any':
        yield Report(any(rt._keyboard.values()))
        return
    pressed = rt._keyboard.get(key_name.lower(), False)
    yield Report(pressed)


def sensing_askandwait(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Ask a question and wait for an answer.

    Sets ``tgt.say_text`` to the question (like a think bubble), then waits
    until ``rt._answer`` is set (by the UI/renderer).
    """
    question = _str(rt.val(tgt, block, 'QUESTION'))
    tgt.say_text = question or None
    rt._answer = None  # reset
    # Yield until answer is provided
    while rt._answer is None:
        yield YIELD
    tgt.say_text = None


def sensing_answer(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    ans = getattr(rt, '_answer', None)
    yield Report('' if ans is None else ans)


def sensing_resettimer(rt: Runtime, tgt: Target, block: Block) -> None:
    rt.clock.reset()


def sensing_timer(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(rt.clock.now())


def sensing_coloristouchingcolor(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Color touching color (simplified: no-op)."""
    yield Report(False)


def sensing_distanceto(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Distance to _mouse_ or another sprite."""
    dest = block.fields.get('DISTANCETOMENU')
    dest_name = _field_val(dest) if dest else '_mouse_'
    if dest_name == '_mouse_':
        dx = tgt.x - rt._mouse_x
        dy = tgt.y - rt._mouse_y
        yield Report(math.sqrt(dx * dx + dy * dy))
        return
    other = rt.get_target_by_name(dest_name)
    if other:
        dx = tgt.x - other.x
        dy = tgt.y - other.y
        yield Report(math.sqrt(dx * dx + dy * dy))
    else:
        yield Report(DISTANCE_UNREACHABLE)


def sensing_of(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Attribute of a sprite or stage (x, y, direction, costume#, size, variable)."""
    prop = rt.val(tgt, block, 'PROPERTY')
    obj_menu = block.fields.get('OBJECT')
    obj_name = _field_val(obj_menu) if obj_menu else ''
    obj = rt.get_target_by_name(obj_name) if obj_name else None
    if obj is None:
        obj = tgt
    prop_name = _str(prop) if not isinstance(prop, str) else prop
    match prop_name:
        case 'x' | 'x position':
            yield Report(obj.x)
        case 'y' | 'y position':
            yield Report(obj.y)
        case 'direction':
            yield Report(obj.direction)
        case 'costume #' | 'costume':
            yield Report(obj.costume_index + 1)
        case 'costume name':
            yield Report(obj.current_costume_name)
        case 'size':
            yield Report(obj.size)
        case 'volume':
            yield Report(obj.volume)
        case 'backdrop name':
            yield Report(obj.current_costume_name if obj.is_stage else '')
        case 'backdrop #' | 'background #':
            yield Report((obj.costume_index + 1) if obj.is_stage else 0)
        case _:
            var = obj.lookup_variable(prop_name)
            yield Report(var.value if var else 0)


def sensing_mousex(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(rt._mouse_x)

def sensing_mousey(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(rt._mouse_y)

def sensing_setdragmode(rt: Runtime, tgt: Target, block: Block) -> None:
    drag = block.fields.get('DRAG_MODE')
    if drag:
        tgt.draggable = _field_val(drag) == 'draggable'


def sensing_mousedown(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(rt._mouse_down)

def sensing_current(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    lt = time.localtime()
    menu = block.fields.get('CURRENTMENU')
    opt = _field_val(menu) if menu else ''
    match opt:
        case 'YEAR':
            yield Report(lt.tm_year)
        case 'MONTH':
            yield Report(lt.tm_mon)
        case 'DATE':
            yield Report(lt.tm_mday)
        case 'DAYOFWEEK':
            yield Report((lt.tm_wday + 1) % 7 + 1)
        case 'HOUR':
            yield Report(lt.tm_hour)
        case 'MINUTE':
            yield Report(lt.tm_min)
        case 'SECOND':
            yield Report(lt.tm_sec)
        case _:
            yield Report(0)


def sensing_dayssince2000(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Days since 2000-01-01 (Scratch-compatible)."""
    epoch = time.mktime(YEAR_2000_EPOCH)
    # Adjust for timezone offset (mktime assumes local time, so epoch includes DST/UTC offset)
    now = time.time()
    is_dst = time.localtime(now).tm_isdst
    offset = time.timezone
    if is_dst > 0:
        offset -= DST_OFFSET_SECS
    yield Report((now - epoch + offset) / SECONDS_PER_DAY)

def sensing_loudness(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(0)


def sensing_loud(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(False)


def sensing_online(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report(True)


def sensing_username(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report('Scratcher')


def sensing_userid(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield Report('')


# ═══════════════════════════════════════════════════════════════════════
#  SOUND
# ═══════════════════════════════════════════════════════════════════════


def _find_sound(tgt: Target, name: str) -> Sound | None:
    """Find a sound on the target by name."""
    return tgt.find_sound(name)


def _ensure_sound_loaded(sound: Sound) -> bool:
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


def sound_sounds_menu(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Menu block: sound name dropdown."""
    name = _field_val(block.fields.get('SOUND_MENU')) if block.fields else ''
    yield Report(name)


def sound_play(rt: Runtime, tgt: Target, block: Block) -> None:
    """Play a sound (fire-and-forget)."""
    name = _str(rt.val(tgt, block, 'SOUND_MENU'))
    sound_obj = _find_sound(tgt, name)
    if sound_obj is None or not _ensure_sound_loaded(sound_obj):
        return
    channel = sound_obj.sound.play()
    if channel:
        channel.set_volume(max(0.0, min(1.0, tgt.volume / 100.0)))


def sound_playuntildone(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
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
    if pygame.mixer.get_init():
        pygame.mixer.stop()


def sound_setvolumeto(rt: Runtime, tgt: Target, block: Block) -> None:
    v = max(VOLUME_MIN, min(VOLUME_MAX, rt.num(tgt, block, 'VOLUME')))
    tgt.volume = v


def sound_changevolumeby(rt: Runtime, tgt: Target, block: Block) -> None:
    delta = rt.num(tgt, block, 'VOLUME')
    tgt.volume = max(VOLUME_MIN, min(VOLUME_MAX, tgt.volume + delta))


def sound_volume(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Reporter: current volume."""
    yield Report(tgt.volume)


def _clamp_effect(effect: str, value: float) -> float:
    """Clamp a sound effect value."""
    if effect == SOUND_EFFECT_PITCH:
        return max(PITCH_MIN, min(PITCH_MAX, value))
    if effect == SOUND_EFFECT_PAN:
        return max(PAN_MIN, min(PAN_MAX, value))
    return value

def sound_seteffectto(rt: Runtime, tgt: Target, block: Block) -> None:
    effect = _field_val(block.fields.get('EFFECT')) if block.fields else ''
    value = rt.num(tgt, block, 'VALUE')
    if effect in (SOUND_EFFECT_PITCH, SOUND_EFFECT_PAN):
        tgt.sound_effects[effect] = _clamp_effect(effect, value)


def sound_changeeffectby(rt: Runtime, tgt: Target, block: Block) -> None:
    effect = _field_val(block.fields.get('EFFECT')) if block.fields else ''
    delta = rt.num(tgt, block, 'VALUE')
    if effect in (SOUND_EFFECT_PITCH, SOUND_EFFECT_PAN):
        tgt.sound_effects[effect] = _clamp_effect(effect, tgt.sound_effects.get(effect, 0.0) + delta)


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


def sound_tempo(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Reporter: current tempo."""
    stage = rt.stage
    yield Report(stage.tempo if stage else DEFAULT_TEMPO_BPM)

# ═══════════════════════════════════════════════════════════════════════
#  PEN
# ═══════════════════════════════════════════════════════════════════════


def pen_pen_down(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.pen_down = True


def pen_pen_up(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.pen_down = False


def pen_set_pen_color_to_color(rt: Runtime, tgt: Target, block: Block) -> None:
    color = rt.val(tgt, block, 'COLOR')
    if isinstance(color, (int, float)):
        color = int(color) & 0xFFFFFF
        red = (color >> 16) & 0xFF
        green = (color >> 8) & 0xFF
        blue = color & 0xFF
        tgt.pen_color = (red, green, blue)
    elif isinstance(color, str):
        color = color.strip().lstrip('#')
        if color.startswith('0x') or color.startswith('0X'):
            color = int(color, 16) & 0xFFFFFF
            red = (color >> 16) & 0xFF
            green = (color >> 8) & 0xFF
            blue = color & 0xFF
            tgt.pen_color = (red, green, blue)
        elif len(color) == 6:
            try:
                val = int(color, 16)
                tgt.pen_color = ((val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF)
            except ValueError:
                pass


def pen_change_pen_size_by(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.pen_size = max(PEN_SIZE_MIN, tgt.pen_size + rt.num(tgt, block, 'SIZE'))


def pen_set_pen_size_to(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.pen_size = max(PEN_SIZE_MIN, rt.num(tgt, block, 'SIZE'))


def pen_clear(rt: Runtime, tgt: Target, block: Block) -> None:
    """Clear pen layer. Handled by the renderer."""
    if rt.stage:
        rt.stage._pen_clear_requested = True


def pen_stamp(rt: Runtime, tgt: Target, block: Block) -> None:
    """Stamp the current costume onto the pen layer."""
    if rt.stage:
        if not hasattr(rt.stage, '_stamp_queue'):
            rt.stage._stamp_queue = []
        rt.stage._stamp_queue.append((tgt.x, tgt.y, tgt.size, tgt.direction, tgt.costume_index))


# ═══════════════════════════════════════════════════════════════════════
#  PROCEDURES (custom blocks — simplified)
# ═══════════════════════════════════════════════════════════════════════


def procedures_definition(rt: Runtime, tgt: Target, block: Block) -> None:
    """Custom block definition — hat. The body runs normally via next block."""
    pass

def procedures_call(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Custom block call — looks up the prototype and runs its body."""
    mutation = getattr(block, 'mutation', None) or getattr(block, '_mutation', None)
    if mutation is None:
        return
    proccode = getattr(mutation, 'proccode', None) or (
        mutation.get('proccode') if isinstance(mutation, dict) else None
    )
    if proccode is None:
        return
    for bid, b in list(tgt.blocks.items()):
        if b.opcode in ('procedures_definition', 'procedures_def'):
            b_mut = getattr(b, 'mutation', None) or getattr(b, '_mutation', None)
            if b_mut:
                b_proc = getattr(b_mut, 'proccode', None) or (
                    b_mut.get('proccode') if isinstance(b_mut, dict) else None
                )
                if b_proc == proccode:
                    frame = rt.current_thread.peek_frame() if rt.current_thread else None
                    if frame is not None:
                        try:
                            arg_ids = json.loads(mutation.argumentids)
                            arg_names = json.loads(b_mut.argumentnames)
                            try:
                                arg_defaults = json.loads(b_mut.argumentdefaults)
                            except (json.JSONDecodeError, AttributeError, TypeError):
                                arg_defaults = []
                            for i, (arg_id, arg_name) in enumerate(zip(arg_ids, arg_names)):
                                if arg_id in block.inputs:
                                    frame.saved[arg_name] = rt.val(tgt, block, arg_id)
                                else:
                                    default = arg_defaults[i] if i < len(arg_defaults) else ''
                                    frame.saved[arg_name] = default
                        except (json.JSONDecodeError, AttributeError, TypeError, KeyError):
                            pass
                    yield from rt.execute_substack(tgt, b.next)
                    return


def argument_reporter_string_number(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Return the value of a custom block argument (string or number)."""
    arg_name = _field_val(block.fields.get('VALUE')) if block.fields.get('VALUE') else ''
    if arg_name:
        frame = rt.current_thread.peek_frame() if rt.current_thread else None
        if frame is not None and arg_name in frame.saved:
            yield Report(frame.saved[arg_name])
            return
    yield Report(0)


def argument_reporter_boolean(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Return the value of a custom block argument (boolean)."""
    arg_name = _field_val(block.fields.get('VALUE')) if block.fields.get('VALUE') else ''
    if arg_name:
        frame = rt.current_thread.peek_frame() if rt.current_thread else None
        if frame is not None and arg_name in frame.saved:
            yield Report(frame.saved[arg_name])
            return
    yield Report(0)




# ═══════════════════════════════════════════════════════════════════════
#  ALL-OPCODES REGISTRY
# ═══════════════════════════════════════════════════════════════════════

OPCODE_MAP: dict[str, Handler] = {
    # Control
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
    'control_start_as_clone': control_start_as_clone,
    'control_all_at_once': control_all_at_once,
    'control_stop': control_stop,
    # Events
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
    # Motion
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
    # Looks
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
    # Operators
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
    # Data — variables
    'data_setvariableto': data_setvariableto,
    'data_changevariableby': data_changevariableby,
    'data_showvariable': data_showvariable,
    'data_hidevariable': data_hidevariable,
    'data_variable': data_variable,
    # Data — lists
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
    # Sensing
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
    # Sound
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
    # Pen
    'pen_penDown': pen_pen_down,
    'pen_penUp': pen_pen_up,
    'pen_setPenColorToColor': pen_set_pen_color_to_color,
    'pen_changePenSizeBy': pen_change_pen_size_by,
    'pen_setPenSizeTo': pen_set_pen_size_to,
    'pen_clear': pen_clear,
    'pen_stamp': pen_stamp,
    # Procedures
    'procedures_def': procedures_definition,  # legacy name
    'procedures_definition': procedures_definition,
    'procedures_call': procedures_call,
    'argument_reporter_string_number': argument_reporter_string_number,
    'argument_reporter_boolean': argument_reporter_boolean,
    'procedures_prototype': procedures_definition,
    'looks_backdrops': looks_backdrops,
}
