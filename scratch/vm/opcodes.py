"""
Opcodes — the actual block implementations for the Scratch VM.

Each handler is a generator function ``(runtime, target, block) -> Generator``.
* Stack blocks end normally (``StopIteration``) when done.
* Reporter blocks ``yield report(value)``.
* Blocks that need to pause ``yield YIELD`` or ``yield wait_yield(secs)``.
"""

from __future__ import annotations

import math
import random
from collections.abc import Generator
from typing import Any

from .runtime import Handler, Runtime, report
from .target import Target
from .thread import YIELD, wait_yield
from .types import Block, Input

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
    - If either converts to NaN (or whitespace), compare case-insensitively as strings.
    - Infinity special-cases handled.
    """
    n1 = _num(v1)
    n2 = _num(v2)
    # Whitespace-only strings → treat as NaN
    if n1 == 0 and isinstance(v1, str) and v1.strip() == '':
        n1 = float('nan')
    if n2 == 0 and isinstance(v2, str) and v2.strip() == '':
        n2 = float('nan')
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
    dur = rt.resolve_num(tgt, block.inputs.get('DURATION'))
    yield wait_yield(dur)


def control_repeat(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    count = round(rt.resolve_num(tgt, block.inputs.get('TIMES')))
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
    cond = rt.resolve_bool(tgt, block.inputs.get('CONDITION'))
    sub_id = _substack_val(block.inputs.get('SUBSTACK'))
    if cond and sub_id:
        yield from rt.execute_substack(tgt, sub_id)


def control_if_else(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    cond = rt.resolve_bool(tgt, block.inputs.get('CONDITION'))
    if cond:
        sub_id = _substack_val(block.inputs.get('SUBSTACK'))
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
    else:
        sub_id = _substack_val(block.inputs.get('SUBSTACK2'))
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)


def control_wait_until(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    cond = block.inputs.get('CONDITION')
    while not rt.resolve_bool(tgt, cond):
        yield YIELD


def control_repeat_until(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    cond = block.inputs.get('CONDITION')
    substack = block.inputs.get('SUBSTACK')
    while not rt.resolve_bool(tgt, cond):
        if substack and substack.value:
            yield from rt.execute_substack(tgt, substack.value)
        yield YIELD


def control_stop(rt: Runtime, tgt: Target, block: Block) -> None:
    """Stop behaviour: stop all | this script | other scripts in sprite."""
    option = block.fields.get('STOP_OPTION')
    choice = option.value if option else 'all'
    _cur = rt.current_thread
    if choice == 'all':
        for th in list(rt.threads):
            th.status = 'done'
    elif choice == 'this script':
        if _cur is not None:
            _cur.status = 'done'
    elif choice == 'other scripts in sprite':
        for th in list(rt.threads):
            if th.target is tgt and th is not _cur:
                th.status = 'done'


def control_while(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    substack = block.inputs.get('SUBSTACK')
    while rt.resolve_bool(tgt, block.inputs.get('CONDITION')):
        if substack and substack.value:
            yield from rt.execute_substack(tgt, substack.value)
        yield YIELD


def control_for_each(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    var_field = block.fields.get('VARIABLE')
    var_name = _field_val(var_field) if var_field else ''
    var = tgt.lookup_variable(var_name) if var_name else None
    if var is None:
        return
    from_val = round(rt.resolve_num(tgt, block.inputs.get('FROM')))
    to_val = round(rt.resolve_num(tgt, block.inputs.get('TO')))
    step = 1 if from_val <= to_val else -1
    for i in range(from_val, to_val + step, step):
        var.value = i
        sub_id = _substack_val(block.inputs.get('SUBSTACK'))
        if sub_id:
            yield from rt.execute_substack(tgt, sub_id)
        yield YIELD


def control_get_counter(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield report(rt._for_each_counter)


def control_incr_counter(rt: Runtime, tgt: Target, block: Block) -> None:
    rt._for_each_counter += 1


def control_clear_counter(rt: Runtime, tgt: Target, block: Block) -> None:
    rt._for_each_counter = 0


# ═══════════════════════════════════════════════════════════════════════
#  EVENT
# ═══════════════════════════════════════════════════════════════════════


def event_whenflagclicked(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — the scheduler starts the next block directly."""
    pass


def event_whenbroadcastreceived(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by broadcast."""
    pass


def event_whenkeypressed(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Hat — triggered by key press."""
    yield from ()


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
        yield report(False)
        return
    # _touching_object_check is defined later in this file;
    # at call time it's resolved.
    yield report(_touching_object_check(rt, tgt, obj_name))


def event_whengreaterthan(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Edge-activated hat — returns True when timer/loudness > VALUE."""
    option = block.fields.get('WHENGREATERTHANMENU')
    opt = _field_val(option) if option else ''
    value = rt.resolve_num(tgt, block.inputs.get('VALUE'))
    if opt == 'timer':
        yield report(rt.clock.now() > value)
    elif opt == 'loudness':
        yield report(False)  # no microphone
    else:
        yield report(False)


def event_broadcast(rt: Runtime, tgt: Target, block: Block) -> None:
    msg = block.fields.get('BROADCAST_INPUT') or block.inputs.get('BROADCAST_INPUT')
    rt.broadcast(_field_val(msg))


def event_broadcastandwait(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    msg = _str(
        rt.resolve_input(
            tgt, block.fields.get('BROADCAST_INPUT') or block.inputs.get('BROADCAST_INPUT')
        )
    )
    started = rt.broadcast(msg)
    # Yield until all started threads are done
    while any(th for th in started if th.status != 'done' and th in rt.threads):
        yield YIELD


# ═══════════════════════════════════════════════════════════════════════
#  MOTION
# ═══════════════════════════════════════════════════════════════════════


def motion_movesteps(rt: Runtime, tgt: Target, block: Block) -> None:
    steps = rt.resolve_num(tgt, block.inputs.get('STEPS'))
    rad = math.radians(90 - tgt.direction)
    tgt.set_xy(tgt.x + steps * math.cos(rad), tgt.y + steps * math.sin(rad))


def _target_xy(rt: Runtime, target_name: str) -> tuple[float, float] | None:
    """Resolve a target name to (x, y) for go-to / point-towards."""
    if target_name == '_mouse_':
        return (0.0, 0.0)
    if target_name == '_random_':
        return (round(random.uniform(-240.0, 240.0)), round(random.uniform(-180.0, 180.0)))
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
        rt.resolve_num(tgt, block.inputs.get('X')), rt.resolve_num(tgt, block.inputs.get('Y'))
    )


def motion_gox(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.x = rt.resolve_num(tgt, block.inputs.get('X'))


def motion_goy(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.y = rt.resolve_num(tgt, block.inputs.get('Y'))


def motion_setx(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.x = rt.resolve_num(tgt, block.inputs.get('X'))


def motion_sety(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.y = rt.resolve_num(tgt, block.inputs.get('Y'))


def motion_changexby(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.x = tgt.x + rt.resolve_num(tgt, block.inputs.get('DX'))


def motion_changeyby(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.y = tgt.y + rt.resolve_num(tgt, block.inputs.get('DY'))


def motion_setdirection(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.direction = rt.resolve_num(tgt, block.inputs.get('DIRECTION'))


def motion_pointindirection(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.direction = rt.resolve_num(tgt, block.inputs.get('DIRECTION'))


def motion_pointtowards(rt: Runtime, tgt: Target, block: Block) -> None:
    target_name = _str(block.fields.get('TOWARDS'))
    if target_name == '_random_':
        tgt.direction = round(random.uniform(-180, 180))
        return
    xy = _target_xy(rt, target_name)
    if xy is None:
        return
    dx = xy[0] - tgt.x
    dy = xy[1] - tgt.y
    direction = 90 - math.degrees(math.atan2(dy, dx))
    tgt.direction = direction


def motion_turnright(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.direction -= rt.resolve_num(tgt, block.inputs.get('DEGREES'))


def motion_turnleft(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.direction += rt.resolve_num(tgt, block.inputs.get('DEGREES'))


def motion_ifonedgebounce(rt: Runtime, tgt: Target, block: Block) -> None:
    if not tgt.costume or tgt.costume.surface is None:
        return
    surf = tgt.costume.surface
    w, h = surf.get_width(), surf.get_height()
    left = -240 + w / 2
    right = 240 - w / 2
    top = 180 - h / 2
    bottom = -180 + h / 2
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
        tgt.direction = 180 - tgt.direction


def motion_setrotationstyle(rt: Runtime, tgt: Target, block: Block) -> None:
    style = block.fields.get('STYLE')
    if style:
        tgt.rotation_style = style.value


def motion_xposition(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield report(tgt.x)


def motion_yposition(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield report(tgt.y)


def motion_direction(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield report(tgt.direction)


def motion_glideto(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    secs = rt.resolve_num(tgt, block.inputs.get('SECS'))
    x = rt.resolve_num(tgt, block.inputs.get('X'))
    y = rt.resolve_num(tgt, block.inputs.get('Y'))
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
        tgt.current_costume = idx
        return
    if isinstance(requested, (int, float)):
        # Numbers → treat as 1-based index
        if math.isnan(requested) or math.isinf(requested):
            idx = 0
        else:
            idx = int(requested) - 1
        idx %= n
        tgt.costume_index = idx
        tgt.current_costume = idx
        return
    # String
    s = _str(requested)
    if s in ('', ' ', '  ', '   ', '    '):
        return  # whitespace → no-op
    # Try name match first
    for i, c in enumerate(tgt.costumes):
        if c.name == s:
            tgt.costume_index = i
            tgt.current_costume = i
            return
    if s == 'next costume':
        tgt.costume_index = (tgt.costume_index + 1) % n
        tgt.current_costume = tgt.costume_index
        return
    if s == 'previous costume':
        tgt.costume_index = (tgt.costume_index - 1) % n
        tgt.current_costume = tgt.costume_index
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
        tgt.current_costume = idx
    except (ValueError, TypeError):
        pass


def looks_switchcostumeto(rt: Runtime, tgt: Target, block: Block) -> None:
    val = rt.resolve_input(tgt, block.inputs.get('COSTUME'))
    _set_costume(tgt, val)


def looks_nextcostume(rt: Runtime, tgt: Target, block: Block) -> None:
    _set_costume(tgt, tgt.costume_index + 2)  # +2 because _set_costume is 1-based


def looks_show(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.visible = True


def looks_hide(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.visible = False


def looks_gotofront(rt: Runtime, tgt: Target, block: Block) -> None:
    max_layer = max((o.layer_order for o in rt.sprite_targets()), default=0)
    tgt.layer_order = max_layer + 1


def looks_goforwardbackwardlayers(rt: Runtime, tgt: Target, block: Block) -> None:
    num = int(rt.resolve_num(tgt, block.inputs.get('NUM')))
    direction = block.fields.get('FORWARD_BACKWARD')
    if direction and direction.value == 'backward':
        num = -num
    tgt.layer_order += num


def looks_setsizeto(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.size = rt.resolve_num(tgt, block.inputs.get('SIZE'))


def looks_changesizeby(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.size += rt.resolve_num(tgt, block.inputs.get('CHANGE'))


def looks_costumenumbername(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    numname = block.fields.get('NUMBER_NAME')
    if numname and numname.value == 'number':
        yield report(tgt.costume_index + 1)
    else:
        yield report(tgt.current_costume_name)


def looks_backdropnumbername(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    numname = block.fields.get('NUMBER_NAME')
    if numname and numname.value == 'number':
        yield report(tgt.costume_index + 1)
    else:
        yield report(tgt.current_costume_name)

    yield report(tgt.current_costume_name)


def looks_switchbackdropto(rt: Runtime, tgt: Target, block: Block) -> None:
    """Switch backdrop (on the stage, not the sprite)."""
    if rt.stage is None:
        return
    val = rt.resolve_input(tgt, block.inputs.get('BACKDROP'))
    s = _str(val)
    n = len(rt.stage.costumes)
    if n == 0:
        return
    # Try name match
    for i, c in enumerate(rt.stage.costumes):
        if c.name == s:
            rt.stage.costume_index = i
            rt.stage.current_costume = i
            return
    if s == 'next backdrop':
        rt.stage.costume_index = (rt.stage.costume_index + 1) % n
        rt.stage.current_costume = rt.stage.costume_index
        return
    if s == 'previous backdrop':
        rt.stage.costume_index = (rt.stage.costume_index - 1) % n
        rt.stage.current_costume = rt.stage.costume_index
        return
    if s == 'random backdrop' and n > 1:
        idx = rt.stage.costume_index
        while idx == rt.stage.costume_index:
            idx = random.randint(0, n - 1)
        rt.stage.costume_index = idx
        rt.stage.current_costume = idx
        return
    # Fall through to _set_costume for number/other string parsing
    _set_costume(rt.stage, val)


def _format_bubble_text(text: Any) -> str:
    """Scratch-compatible bubble text formatting.

    - Numbers rounded to 2 decimal places (unless < 0.01 or integer).
    - Truncated at 330 characters.
    """
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        if text % 1 == 0:
            s = str(int(text))
        elif abs(text) >= 0.01:
            s = f'{text:.2f}'
        else:
            s = str(text)
    else:
        s = str(text) if text is not None else ''
    return s[:330]


def looks_say(rt: Runtime, tgt: Target, block: Block) -> None:
    msg = rt.resolve_input(tgt, block.inputs.get('MESSAGE'))
    tgt.say_text = _format_bubble_text(msg) or None


def looks_sayforsecs(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    msg = rt.resolve_input(tgt, block.inputs.get('MESSAGE'))
    secs = rt.resolve_num(tgt, block.inputs.get('SECS'))
    tgt.say_text = _format_bubble_text(msg) or None
    if secs > 0:
        tgt.say_until = rt.clock._tick + rt.clock.frames_for(secs)
        yield wait_yield(secs)
    tgt.say_text = None
    tgt.say_until = None


# ═══════════════════════════════════════════════════════════════════════
#  OPERATORS
# ═══════════════════════════════════════════════════════════════════════


def operator_add(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_num(tgt, block.inputs.get('NUM1'))
    b = rt.resolve_num(tgt, block.inputs.get('NUM2'))
    yield report(a + b)


def operator_subtract(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_num(tgt, block.inputs.get('NUM1'))
    b = rt.resolve_num(tgt, block.inputs.get('NUM2'))
    yield report(a - b)


def operator_multiply(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_num(tgt, block.inputs.get('NUM1'))
    b = rt.resolve_num(tgt, block.inputs.get('NUM2'))
    yield report(a * b)


def operator_divide(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_num(tgt, block.inputs.get('NUM1'))
    b = rt.resolve_num(tgt, block.inputs.get('NUM2'))
    # _num handles Infinity/INFINITY distinction already
    yield report(a / b if b != 0 else float('inf'))


def operator_lt(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_input(tgt, block.inputs.get('OPERAND1'))
    b = rt.resolve_input(tgt, block.inputs.get('OPERAND2'))
    yield report(_scratch_compare(a, b) < 0)


def operator_equals(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_input(tgt, block.inputs.get('OPERAND1'))
    b = rt.resolve_input(tgt, block.inputs.get('OPERAND2'))
    yield report(_scratch_compare(a, b) == 0)


def operator_gt(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_input(tgt, block.inputs.get('OPERAND1'))
    b = rt.resolve_input(tgt, block.inputs.get('OPERAND2'))
    yield report(_scratch_compare(a, b) > 0)


def operator_and(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_bool(tgt, block.inputs.get('OPERAND1'))
    b = rt.resolve_bool(tgt, block.inputs.get('OPERAND2'))
    yield report(a and b)


def operator_or(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_bool(tgt, block.inputs.get('OPERAND1'))
    b = rt.resolve_bool(tgt, block.inputs.get('OPERAND2'))
    yield report(a or b)


def operator_not(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_bool(tgt, block.inputs.get('OPERAND'))
    yield report(not a)


def operator_random(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    lo = rt.resolve_num(tgt, block.inputs.get('FROM'))
    hi = rt.resolve_num(tgt, block.inputs.get('TO'))
    if lo > hi:
        lo, hi = hi, lo
    lo_int, hi_int = int(lo), int(hi)
    if lo == lo_int and hi == hi_int:
        yield report(random.randint(lo_int, hi_int))
    else:
        yield report(random.uniform(lo, hi))


def operator_join(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = _str(rt.resolve_input(tgt, block.inputs.get('STRING1')))
    b = _str(rt.resolve_input(tgt, block.inputs.get('STRING2')))
    yield report(a + b)


def operator_letter_of(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    idx = int(rt.resolve_num(tgt, block.inputs.get('LETTER')))
    s = _str(rt.resolve_input(tgt, block.inputs.get('STRING')))
    if 1 <= idx <= len(s):
        yield report(s[idx - 1])
    yield report('')


def operator_length(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    s = _str(rt.resolve_input(tgt, block.inputs.get('STRING')))
    yield report(len(s))


def operator_contains(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    s1 = _str(rt.resolve_input(tgt, block.inputs.get('STRING1')))
    s2 = _str(rt.resolve_input(tgt, block.inputs.get('STRING2')))
    # Scratch comparison: case-insensitive
    yield report(s2.lower() in s1.lower())


def operator_mod(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    a = rt.resolve_num(tgt, block.inputs.get('NUM1'))
    b = rt.resolve_num(tgt, block.inputs.get('NUM2'))
    yield report(a % b if b != 0 else float('nan'))


def operator_round(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    n = rt.resolve_num(tgt, block.inputs.get('NUM'))
    yield report(round(n))


def operator_mathop(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    op = block.fields.get('OPERATOR')
    n = rt.resolve_num(tgt, block.inputs.get('NUM'))
    if op is None:
        yield report(0)
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
            r = math.sin(math.radians(n))
        case 'cos':
            r = math.cos(math.radians(n))
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
        case 'e^':
            r = math.exp(n)
        case '10^':
            r = math.pow(10, n)
        case _:
            r = 0
    yield report(r)


# ═══════════════════════════════════════════════════════════════════════
#  DATA — Variables
# ═══════════════════════════════════════════════════════════════════════


def data_setvariableto(rt: Runtime, tgt: Target, block: Block) -> None:
    var_name = _field_val(block.fields.get('VARIABLE'))
    value = rt.resolve_input(tgt, block.inputs.get('VALUE'))
    if var_name:
        var = tgt.lookup_variable(var_name)
        if var is None and rt.stage:
            var = rt.stage.lookup_variable(var_name)
        if var:
            var.value = value


def data_changevariableby(rt: Runtime, tgt: Target, block: Block) -> None:
    var_name = _field_val(block.fields.get('VARIABLE'))
    delta = rt.resolve_num(tgt, block.inputs.get('VALUE'))
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
            yield report(var.value)
    yield report(0)


# ═══════════════════════════════════════════════════════════════════════
#  DATA — Lists
# ═══════════════════════════════════════════════════════════════════════


def data_addtolist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.resolve_input(tgt, block.inputs.get('ITEM'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            lst.contents.append(item)


def data_deleteoflist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    idx = int(rt.resolve_num(tgt, block.inputs.get('INDEX')))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst and 1 <= idx <= len(lst.contents):
            del lst.contents[idx - 1]


def data_insertatlist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.resolve_input(tgt, block.inputs.get('ITEM'))
    idx = int(rt.resolve_num(tgt, block.inputs.get('INDEX')))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            lst.contents.insert(max(0, idx - 1), item)


def data_replaceitemoflist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.resolve_input(tgt, block.inputs.get('ITEM'))
    idx = int(rt.resolve_num(tgt, block.inputs.get('INDEX')))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst and 1 <= idx <= len(lst.contents):
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
    idx = int(rt.resolve_num(tgt, block.inputs.get('INDEX')))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst and 1 <= idx <= len(lst.contents):
            yield report(lst.contents[idx - 1])
    yield report('')


def data_lengthoflist(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    list_name = _field_val(block.fields.get('LIST'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            yield report(len(lst.contents))
    yield report(0)


def data_listcontainsitem(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.resolve_input(tgt, block.inputs.get('ITEM'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            # Scratch comparison: case-insensitive, type-insensitive
            yield report(any(_scratch_compare(item, x) == 0 for x in lst.contents))
    yield report(False)


def data_itemnumoflist(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.resolve_input(tgt, block.inputs.get('ITEM'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            for i, x in enumerate(lst.contents, 1):
                if _scratch_compare(item, x) == 0:
                    yield report(i)
    yield report(0)


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
            tgt.x + left_ < -240
            or tgt.x + right_ > 240
            or tgt.y + bottom_ < -180
            or tgt.y + top_ > 180
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
        if obj_input:
            obj_name = _str(rt.resolve_input(tgt, obj_input))
        else:
            obj_name = '_mouse_'
    else:
        obj_name = obj.value
    yield report(_touching_object_check(rt, tgt, obj_name))


def sensing_touchingcolor(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield report(False)  # simplified


def sensing_keypressed(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    key_name = _field_val(block.fields.get('KEY_OPTION'))
    pressed = rt._keyboard.get(key_name.lower(), False) if hasattr(rt, '_keyboard') else False
    yield report(pressed)


def sensing_askandwait(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Ask a question and wait for an answer.

    Sets ``tgt.say_text`` to the question (like a think bubble), then waits
    until ``rt._answer`` is set (by the UI/renderer).
    """
    question = _str(rt.resolve_input(tgt, block.inputs.get('QUESTION')))
    tgt.say_text = question or None
    rt._answer = None  # reset
    # Yield until answer is provided
    while rt._answer is None:
        yield YIELD
    tgt.say_text = None


def sensing_answer(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield report(getattr(rt, '_answer', ''))


def sensing_resettimer(rt: Runtime, tgt: Target, block: Block) -> None:
    rt.clock.reset()


def sensing_timer(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    yield report(rt.clock.now())


# ═══════════════════════════════════════════════════════════════════════
#  PEN
# ═══════════════════════════════════════════════════════════════════════


def pen_pen_down(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.pen_down = True


def pen_pen_up(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.pen_down = False


def pen_set_pen_color_to_color(rt: Runtime, tgt: Target, block: Block) -> None:
    color = rt.resolve_input(tgt, block.inputs.get('COLOR'))
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
    tgt.pen_size = max(0, tgt.pen_size + rt.resolve_num(tgt, block.inputs.get('SIZE')))


def pen_set_pen_size_to(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.pen_size = max(0, rt.resolve_num(tgt, block.inputs.get('SIZE')))


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
    # Simplified: find the definition in the target's blocks by proccode
    # and jump to its body.
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
                    yield from rt.execute_substack(tgt, b.next)
                    return
    return
    yield


def argument_reporter_string_number(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Return the value of a custom block argument (string or number)."""
    yield report(0)  # placeholder


def argument_reporter_boolean(rt: Runtime, tgt: Target, block: Block) -> Generator[Any]:
    """Return the value of a custom block argument (boolean)."""
    yield report(False)  # placeholder


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
    'motion_glidesecstoxy': motion_glideto,
    'motion_glideto_menu': motion_glideto_menu,
    # Looks
    'looks_switchcostumeto': looks_switchcostumeto,
    'looks_nextcostume': looks_nextcostume,
    'looks_show': looks_show,
    'looks_hide': looks_hide,
    'looks_gotofront': looks_gotofront,
    'looks_goforwardbackwardlayers': looks_goforwardbackwardlayers,
    'looks_setsizeto': looks_setsizeto,
    'looks_changesizeby': looks_changesizeby,
    'looks_costumenumbername': looks_costumenumbername,
    'looks_backdropnumbername': looks_backdropnumbername,
    'looks_switchbackdropto': looks_switchbackdropto,
    'looks_switchbackdroptoandwait': looks_switchbackdropto,
    'looks_say': looks_say,
    'looks_sayforsecs': looks_sayforsecs,
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
    # Sensing
    'sensing_touchingobject': sensing_touchingobject,
    'sensing_touchingcolor': sensing_touchingcolor,
    'sensing_keypressed': sensing_keypressed,
    'sensing_askandwait': sensing_askandwait,
    'sensing_resettimer': sensing_resettimer,
    'sensing_timer': sensing_timer,
    'sensing_answer': sensing_answer,
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
}
