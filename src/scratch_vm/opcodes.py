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
from typing import Any, Generator

from .runtime import Runtime, report
from .thread import YIELD, wait_yield
from .types import Block


# ── Helpers ──────────────────────────────────────────────────────────────

def _num(inp: Any) -> float:
    """Coerce to number; Scratch treats non-numeric as 0."""
    try:
        return float(inp)
    except (ValueError, TypeError):
        return 0.0


def _str(inp: Any) -> str:
    if isinstance(inp, float):
        # Avoid '-0.0' and trailing zeros
        if inp == -0.0:
            inp = 0.0
        s = f'{inp:g}'
        return s
    return str(inp) if inp is not None else ''


def _bool(inp: Any) -> bool:
    if isinstance(inp, str):
        return inp.lower() not in ('', 'false', '0')
    return bool(inp)


def _field_val(field) -> str:
    """Extract the string value from a block field, whether Field or raw."""
    if field is None:
        return ''
    if hasattr(field, 'value'):
        return field.value
    return str(field)


# ═══════════════════════════════════════════════════════════════════════
#  CONTROL
# ═══════════════════════════════════════════════════════════════════════

def control_wait(rt: Runtime, tgt, block: Block) -> Generator:
    dur = rt.resolve_num(tgt, block.inputs.get('DURATION'))
    yield wait_yield(dur)


def control_repeat(rt: Runtime, tgt, block: Block) -> Generator:
    count = int(rt.resolve_num(tgt, block.inputs.get('TIMES')))
    substack = block.inputs.get('SUBSTACK')
    for _ in range(count):
        if substack and substack.value:
            # Use the thread-based sequencer for the substack
            yield from rt.execute_substack(tgt, substack.value)
        yield YIELD


def control_forever(rt: Runtime, tgt, block: Block) -> Generator:
    substack = block.inputs.get('SUBSTACK')
    while True:
        if substack and substack.value:
            yield from rt.execute_substack(tgt, substack.value)
        yield YIELD


def control_if(rt: Runtime, tgt, block: Block) -> Generator:
    cond = rt.resolve_bool(tgt, block.inputs.get('CONDITION'))
    substack = block.inputs.get('SUBSTACK')
    if cond and substack and substack.value:
        yield from rt.execute_substack(tgt, substack.value)


def control_if_else(rt: Runtime, tgt, block: Block) -> Generator:
    cond = rt.resolve_bool(tgt, block.inputs.get('CONDITION'))
    if cond:
        substack = block.inputs.get('SUBSTACK')
        if substack and substack.value:
            yield from rt.execute_substack(tgt, substack.value)
    else:
        substack2 = block.inputs.get('SUBSTACK2')
        if substack2 and substack2.value:
            yield from rt.execute_substack(tgt, substack2.value)


def control_wait_until(rt: Runtime, tgt, block: Block) -> Generator:
    cond = block.inputs.get('CONDITION')
    while not rt.resolve_bool(tgt, cond):
        yield YIELD


def control_repeat_until(rt: Runtime, tgt, block: Block) -> Generator:
    cond = block.inputs.get('CONDITION')
    substack = block.inputs.get('SUBSTACK')
    while not rt.resolve_bool(tgt, cond):
        if substack and substack.value:
            yield from rt.execute_substack(tgt, substack.value)
        yield YIELD


def control_stop(rt: Runtime, tgt, block: Block) -> Generator:
    """Stop behaviour: stop all | this script | other scripts in sprite."""
    option = block.fields.get('STOP_OPTION')
    choice = option.value if option else 'all'
    if choice == 'all':
        # Kill every thread
        for th in list(rt.threads):
            th.status = 'done'
    elif choice == 'this script':
        # Signal done for THIS thread — the sequencer will handle it
        return
    elif choice == 'other scripts in sprite':
        # Kill all threads on this target except the current one
        for th in list(rt.threads):
            if th.target is tgt:
                th.status = 'done'


# ═══════════════════════════════════════════════════════════════════════
#  EVENT
# ═══════════════════════════════════════════════════════════════════════

def event_whenflagclicked(rt: Runtime, tgt, block: Block) -> Generator:
    """Hat — the scheduler starts the next block directly, so this
    never actually runs as a handler."""
    return
    yield  # pragma: no cover — make it a generator


def event_whenbroadcastreceived(rt: Runtime, tgt, block: Block) -> Generator:
    """Hat — same as flag clicked."""
    return
    yield


def event_broadcast(rt: Runtime, tgt, block: Block) -> Generator:
    msg = rt.resolve_input(tgt, block.fields.get('BROADCAST_INPUT')
                           or block.inputs.get('BROADCAST_INPUT'))
    rt.broadcast(_str(msg))


def event_broadcastandwait(rt: Runtime, tgt, block: Block) -> Generator:
    msg = rt.resolve_input(tgt, block.fields.get('BROADCAST_INPUT')
                           or block.inputs.get('BROADCAST_INPUT'))
    msg_str = _str(msg)

    # Check if there's already a thread waiting for this broadcast
    # from the same target — if so, we're already waiting
    existing = [t for t in rt.threads
                if t is not _current_thread(rt)
                and t.target is tgt
                and t.status != 'done'
                and getattr(t, '_broadcast_msg', None) == msg_str]

    if existing:
        # Already waiting
        return

    rt.broadcast(msg_str)

    # Mark all newly created threads so we can wait for them
    new_threads = [t for t in rt.threads
                   if t not in getattr(rt, '_prev_threads', [])
                   and t.status != 'done']

    if new_threads:
        # Yield indefinitely; the scheduler will clean us up when
        # the broadcast threads finish (or we could track them).
        # For now, yield a few frames to let them run.
        for _ in range(10):
            yield YIELD


def _current_thread(rt: Runtime):
    """Heuristic: find the thread this handler is running in.
    Not perfect but works for simple cases."""
    return None


# ═══════════════════════════════════════════════════════════════════════
#  MOTION
# ═══════════════════════════════════════════════════════════════════════

def motion_movesteps(rt: Runtime, tgt, block: Block) -> Generator:
    steps = rt.resolve_num(tgt, block.inputs.get('STEPS'))
    rad = math.radians(tgt.direction)
    tgt.x += steps * math.cos(rad)
    tgt.y += steps * math.sin(rad)


def motion_gotoxy(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.x = rt.resolve_num(tgt, block.inputs.get('X'))
    tgt.y = rt.resolve_num(tgt, block.inputs.get('Y'))


def motion_gox(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.x = rt.resolve_num(tgt, block.inputs.get('X'))


def motion_goy(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.y = rt.resolve_num(tgt, block.inputs.get('Y'))


def motion_setx(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.x = rt.resolve_num(tgt, block.inputs.get('X'))


def motion_sety(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.y = rt.resolve_num(tgt, block.inputs.get('Y'))


def motion_changexby(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.x += rt.resolve_num(tgt, block.inputs.get('DX'))


def motion_changeyby(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.y += rt.resolve_num(tgt, block.inputs.get('DY'))


def motion_setdirection(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.direction = rt.resolve_num(tgt, block.inputs.get('DIRECTION'))


def motion_pointindirection(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.direction = rt.resolve_num(tgt, block.inputs.get('DIRECTION'))


def motion_turnright(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.direction -= rt.resolve_num(tgt, block.inputs.get('DEGREES'))


def motion_turnleft(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.direction += rt.resolve_num(tgt, block.inputs.get('DEGREES'))


def motion_ifonedgebounce(rt: Runtime, tgt, block: Block) -> Generator:
    if not tgt.costume or tgt.costume.surface is None:
        return
    surf = tgt.costume.surface
    w, h = surf.get_width(), surf.get_height()
    # Stage bounds in Scratch coords: -240 to 240 x, -180 to 180 y
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
        tgt.direction = 180 - tgt.direction  # reflect


def motion_setrotationstyle(rt: Runtime, tgt, block: Block) -> Generator:
    style = block.fields.get('STYLE')
    if style:
        tgt.rotation_style = style.value


def motion_xposition(rt: Runtime, tgt, block: Block) -> Generator:
    yield report(tgt.x)


def motion_yposition(rt: Runtime, tgt, block: Block) -> Generator:
    yield report(tgt.y)


def motion_direction(rt: Runtime, tgt, block: Block) -> Generator:
    yield report(tgt.direction)


def motion_glideto(rt: Runtime, tgt, block: Block) -> Generator:
    secs = rt.resolve_num(tgt, block.inputs.get('SECS'))
    dx = rt.resolve_num(tgt, block.inputs.get('X')) - tgt.x
    dy = rt.resolve_num(tgt, block.inputs.get('Y')) - tgt.y
    steps = 30 * secs  # approximate 30 fps
    if steps <= 0:
        return
    for _ in range(int(steps)):
        tgt.x += dx / steps
        tgt.y += dy / steps
        yield YIELD


# ═══════════════════════════════════════════════════════════════════════
#  LOOKS
# ═══════════════════════════════════════════════════════════════════════

def looks_switchcostumeto(rt: Runtime, tgt, block: Block) -> Generator:
    name = _str(rt.resolve_input(tgt, block.inputs.get('COSTUME')))
    for i, c in enumerate(tgt.costumes):
        if c.name == name:
            tgt.costume_index = i
            tgt.current_costume = i
            return
    # Try numeric index
    idx = int(rt.resolve_num(tgt, block.inputs.get('COSTUME')))
    if 1 <= idx <= len(tgt.costumes):
        tgt.costume_index = idx - 1
        tgt.current_costume = idx - 1


def looks_nextcostume(rt: Runtime, tgt, block: Block) -> Generator:
    n = len(tgt.costumes)
    if n > 0:
        tgt.costume_index = (tgt.costume_index + 1) % n
        tgt.current_costume = tgt.costume_index


def looks_show(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.visible = True


def looks_hide(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.visible = False


def looks_gotofront(rt: Runtime, tgt, block: Block) -> Generator:
    max_layer = max((o.layer_order for o in rt.sprite_targets()), default=0)
    tgt.layer_order = max_layer + 1


def looks_goforwardbackwardlayers(rt: Runtime, tgt, block: Block) -> Generator:
    num = int(rt.resolve_num(tgt, block.inputs.get('NUM')))
    direction = block.fields.get('FORWARD_BACKWARD')
    if direction and direction.value == 'backward':
        num = -num
    tgt.layer_order += num


def looks_setsizeto(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.size = rt.resolve_num(tgt, block.inputs.get('SIZE'))


def looks_changesizeby(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.size += rt.resolve_num(tgt, block.inputs.get('CHANGE'))


def looks_costumenumbername(rt: Runtime, tgt, block: Block) -> Generator:
    numname = block.fields.get('NUMBER_NAME')
    if numname and numname.value == 'number':
        yield report(tgt.costume_index + 1)
    else:
        yield report(tgt.current_costume_name)


def looks_backdropnumbername(rt: Runtime, tgt, block: Block) -> Generator:
    numname = block.fields.get('NUMBER_NAME')
    if numname and numname.value == 'number':
        yield report(tgt.costume_index + 1)
    else:
        yield report(tgt.current_costume_name)


def looks_switchbackdropto(rt: Runtime, tgt, block: Block) -> Generator:
    name = _str(rt.resolve_input(tgt, block.inputs.get('BACKDROP')))
    for i, c in enumerate(tgt.costumes):
        if c.name == name:
            tgt.costume_index = i
            return
    idx = int(rt.resolve_num(tgt, block.inputs.get('BACKDROP')))
    if 1 <= idx <= len(tgt.costumes):
        tgt.costume_index = idx - 1


# ═══════════════════════════════════════════════════════════════════════
#  OPERATORS
# ═══════════════════════════════════════════════════════════════════════

def operator_add(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_num(tgt, block.inputs.get('NUM1'))
    b = rt.resolve_num(tgt, block.inputs.get('NUM2'))
    yield report(a + b)


def operator_subtract(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_num(tgt, block.inputs.get('NUM1'))
    b = rt.resolve_num(tgt, block.inputs.get('NUM2'))
    yield report(a - b)


def operator_multiply(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_num(tgt, block.inputs.get('NUM1'))
    b = rt.resolve_num(tgt, block.inputs.get('NUM2'))
    yield report(a * b)


def operator_divide(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_num(tgt, block.inputs.get('NUM1'))
    b = rt.resolve_num(tgt, block.inputs.get('NUM2'))
    yield report(a / b if b != 0 else float('inf'))


def operator_lt(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_num(tgt, block.inputs.get('OPERAND1'))
    b = rt.resolve_num(tgt, block.inputs.get('OPERAND2'))
    yield report(a < b)


def operator_equals(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_input(tgt, block.inputs.get('OPERAND1'))
    b = rt.resolve_input(tgt, block.inputs.get('OPERAND2'))
    yield report(a == b)


def operator_gt(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_num(tgt, block.inputs.get('OPERAND1'))
    b = rt.resolve_num(tgt, block.inputs.get('OPERAND2'))
    yield report(a > b)


def operator_and(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_bool(tgt, block.inputs.get('OPERAND1'))
    b = rt.resolve_bool(tgt, block.inputs.get('OPERAND2'))
    yield report(a and b)


def operator_or(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_bool(tgt, block.inputs.get('OPERAND1'))
    b = rt.resolve_bool(tgt, block.inputs.get('OPERAND2'))
    yield report(a or b)


def operator_not(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_bool(tgt, block.inputs.get('OPERAND'))
    yield report(not a)


def operator_random(rt: Runtime, tgt, block: Block) -> Generator:
    lo = rt.resolve_num(tgt, block.inputs.get('FROM'))
    hi = rt.resolve_num(tgt, block.inputs.get('TO'))
    if lo > hi:
        lo, hi = hi, lo
    lo_int, hi_int = int(lo), int(hi)
    if lo == lo_int and hi == hi_int:
        yield report(random.randint(lo_int, hi_int))
    else:
        yield report(random.uniform(lo, hi))


def operator_join(rt: Runtime, tgt, block: Block) -> Generator:
    a = _str(rt.resolve_input(tgt, block.inputs.get('STRING1')))
    b = _str(rt.resolve_input(tgt, block.inputs.get('STRING2')))
    yield report(a + b)


def operator_letter_of(rt: Runtime, tgt, block: Block) -> Generator:
    idx = int(rt.resolve_num(tgt, block.inputs.get('LETTER')))
    s = _str(rt.resolve_input(tgt, block.inputs.get('STRING')))
    if 1 <= idx <= len(s):
        yield report(s[idx - 1])
    yield report('')


def operator_length(rt: Runtime, tgt, block: Block) -> Generator:
    s = _str(rt.resolve_input(tgt, block.inputs.get('STRING')))
    yield report(len(s))


def operator_contains(rt: Runtime, tgt, block: Block) -> Generator:
    s1 = _str(rt.resolve_input(tgt, block.inputs.get('STRING1')))
    s2 = _str(rt.resolve_input(tgt, block.inputs.get('STRING2')))
    yield report(s2 in s1)


def operator_mod(rt: Runtime, tgt, block: Block) -> Generator:
    a = rt.resolve_num(tgt, block.inputs.get('NUM1'))
    b = rt.resolve_num(tgt, block.inputs.get('NUM2'))
    yield report(a % b if b != 0 else float('nan'))


def operator_round(rt: Runtime, tgt, block: Block) -> Generator:
    n = rt.resolve_num(tgt, block.inputs.get('NUM'))
    yield report(round(n))


def operator_mathop(rt: Runtime, tgt, block: Block) -> Generator:
    op = block.fields.get('OPERATOR')
    n = rt.resolve_num(tgt, block.inputs.get('NUM'))
    if op:
        match op.value:
            case 'abs':       r = abs(n)
            case 'floor':     r = math.floor(n)
            case 'ceiling':   r = math.ceil(n)
            case 'sqrt':      r = math.sqrt(n) if n >= 0 else float('nan')
            case 'sin':       r = math.sin(math.radians(n))
            case 'cos':       r = math.cos(math.radians(n))
            case 'tan':       r = math.tan(math.radians(n)) if n % 180 != 90 else float('inf')
            case 'asin':      r = math.degrees(math.asin(max(-1, min(1, n))))
            case 'acos':      r = math.degrees(math.acos(max(-1, min(1, n))))
            case 'atan':      r = math.degrees(math.atan(n))
            case 'ln':        r = math.log(n) if n > 0 else float('-inf')
            case 'log':       r = math.log10(n) if n > 0 else float('-inf')
            case 'e^':        r = math.exp(n)
            case '10^':       r = math.pow(10, n)
            case _:           r = 0
    else:
        r = 0
    yield report(r)


# ═══════════════════════════════════════════════════════════════════════
#  DATA — Variables
# ═══════════════════════════════════════════════════════════════════════

def data_setvariableto(rt: Runtime, tgt, block: Block) -> Generator:
    var_name = _field_val(block.fields.get('VARIABLE'))
    value = rt.resolve_input(tgt, block.inputs.get('VALUE'))
    if var_name:
        var = tgt.lookup_variable(var_name)
        if var is None and rt.stage:
            var = rt.stage.lookup_variable(var_name)
        if var:
            var.value = value


def data_changevariableby(rt: Runtime, tgt, block: Block) -> Generator:
    var_name = _field_val(block.fields.get('VARIABLE'))
    delta = rt.resolve_num(tgt, block.inputs.get('VALUE'))
    if var_name:
        var = tgt.lookup_variable(var_name)
        if var is None and rt.stage:
            var = rt.stage.lookup_variable(var_name)
        if var:
            var.value = _num(var.value) + delta


def data_showvariable(rt: Runtime, tgt, block: Block) -> Generator:
    # In a real renderer, toggles variable monitor visibility.
    # For now, no-op (display is handled by the renderer).
    pass


def data_hidevariable(rt: Runtime, tgt, block: Block) -> Generator:
    pass


def data_variable(rt: Runtime, tgt, block: Block) -> Generator:
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

def data_addtolist(rt: Runtime, tgt, block: Block) -> Generator:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.resolve_input(tgt, block.inputs.get('ITEM'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            lst.contents.append(item)


def data_deleteoflist(rt: Runtime, tgt, block: Block) -> Generator:
    list_name = _field_val(block.fields.get('LIST'))
    idx = int(rt.resolve_num(tgt, block.inputs.get('INDEX')))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst and 1 <= idx <= len(lst.contents):
            del lst.contents[idx - 1]


def data_insertatlist(rt: Runtime, tgt, block: Block) -> Generator:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.resolve_input(tgt, block.inputs.get('ITEM'))
    idx = int(rt.resolve_num(tgt, block.inputs.get('INDEX')))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            lst.contents.insert(max(0, idx - 1), item)


def data_replaceitemoflist(rt: Runtime, tgt, block: Block) -> Generator:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.resolve_input(tgt, block.inputs.get('ITEM'))
    idx = int(rt.resolve_num(tgt, block.inputs.get('INDEX')))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst and 1 <= idx <= len(lst.contents):
            lst.contents[idx - 1] = item


def data_itemoflist(rt: Runtime, tgt, block: Block) -> Generator:
    list_name = _field_val(block.fields.get('LIST'))
    idx = int(rt.resolve_num(tgt, block.inputs.get('INDEX')))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst and 1 <= idx <= len(lst.contents):
            yield report(lst.contents[idx - 1])
    yield report('')


def data_lengthoflist(rt: Runtime, tgt, block: Block) -> Generator:
    list_name = _field_val(block.fields.get('LIST'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            yield report(len(lst.contents))
    yield report(0)


def data_listcontainsitem(rt: Runtime, tgt, block: Block) -> Generator:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.resolve_input(tgt, block.inputs.get('ITEM'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            yield report(item in lst.contents)
    yield report(False)


# ═══════════════════════════════════════════════════════════════════════
#  SENSING
# ═══════════════════════════════════════════════════════════════════════

def sensing_touchingobject(rt: Runtime, tgt, block: Block) -> Generator:
    # Simplified: uses bounding-box overlap detection
    obj = block.fields.get('TOUCHINGOBJECTMENU')
    if obj is None:
        obj_input = block.inputs.get('TOUCHINGOBJECTMENU')
        if obj_input:
            obj_name = _str(rt.resolve_input(tgt, obj_input))
        else:
            obj_name = '_mouse_'
    else:
        obj_name = obj.value

    if obj_name == '_mouse_':
        # We can't check mouse without the renderer; report False
        yield report(False)
        return

    if obj_name == '_edge_':
        l, t, r, b = tgt.scratch_bounds()
        hit = (tgt.x + l < -240 or tgt.x + r > 240
               or tgt.y + b < -180 or tgt.y + t > 180)
        yield report(hit)
        return

    # Compare bounding boxes with the named sprite
    tgt_bounds = tgt.scratch_bounds()
    for other in rt.sprite_targets():
        if other.name != obj_name:
            continue
        other_bounds = other.scratch_bounds()
        # AABB overlap
        overlap = (
            tgt.x + tgt_bounds[0] < other.x + other_bounds[2]
            and tgt.x + tgt_bounds[2] > other.x + other_bounds[0]
            and tgt.y + tgt_bounds[1] > other.y + other_bounds[3]
            and tgt.y + tgt_bounds[3] < other.y + other_bounds[1]
        )
        if overlap:
            yield report(True)
    yield report(False)


def sensing_touchingcolor(rt: Runtime, tgt, block: Block) -> Generator:
    yield report(False)  # simplified


def sensing_keypressed(rt: Runtime, tgt, block: Block) -> Generator:
    key_obj = block.fields.get('KEY_OPTION')
    key_name = key_obj.value if key_obj else ''
    pressed = rt._keyboard.get(key_name.lower(), False) if hasattr(rt, '_keyboard') else False
    yield report(pressed)


def sensing_askandwait(rt: Runtime, tgt, block: Block) -> Generator:
    # Simplified: no-op
    pass


def sensing_resettimer(rt: Runtime, tgt, block: Block) -> Generator:
    rt.clock.reset()


def sensing_timer(rt: Runtime, tgt, block: Block) -> Generator:
    yield report(rt.clock.now())


# ═══════════════════════════════════════════════════════════════════════
#  PEN
# ═══════════════════════════════════════════════════════════════════════

def pen_penDown(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.pen_down = True


def pen_penUp(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.pen_down = False


def pen_setPenColorToColor(rt: Runtime, tgt, block: Block) -> Generator:
    color = rt.resolve_input(tgt, block.inputs.get('COLOR'))
    if isinstance(color, (int, float)):
        # Scratch colour is 0x00RRGGBB
        color = int(color)
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        tgt.pen_color = (r, g, b)


def pen_changePenSizeBy(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.pen_size += rt.resolve_num(tgt, block.inputs.get('SIZE'))


def pen_setPenSizeTo(rt: Runtime, tgt, block: Block) -> Generator:
    tgt.pen_size = max(0, rt.resolve_num(tgt, block.inputs.get('SIZE')))


def pen_clear(rt: Runtime, tgt, block: Block) -> Generator:
    """Clear pen layer. Handled by the renderer."""
    if rt.stage:
        rt.stage._pen_clear_requested = True


def pen_stamp(rt: Runtime, tgt, block: Block) -> Generator:
    """Stamp the current costume onto the pen layer."""
    if rt.stage:
        if not hasattr(rt.stage, '_stamp_queue'):
            rt.stage._stamp_queue = []
        rt.stage._stamp_queue.append((tgt.x, tgt.y, tgt.size,
                                       tgt.direction, tgt.costume_index))


# ═══════════════════════════════════════════════════════════════════════
#  PROCEDURES (custom blocks — simplified)
# ═══════════════════════════════════════════════════════════════════════

def procedures_def(rt: Runtime, tgt, block: Block) -> Generator:
    """Custom block definition — hat that collects arguments and runs body.
    Not yet fully implemented."""
    return
    yield


def procedures_call(rt: Runtime, tgt, block: Block) -> Generator:
    """Custom block call — looks up the prototype and runs its body."""
    # Simplified: we'd need to resolve mutation references
    return
    yield


# ═══════════════════════════════════════════════════════════════════════
#  ALL-OPCODES REGISTRY
# ═══════════════════════════════════════════════════════════════════════

OPCODE_MAP: dict[str, object] = {
    # Control
    'control_wait': control_wait,
    'control_repeat': control_repeat,
    'control_forever': control_forever,
    'control_if': control_if,
    'control_if_else': control_if_else,
    'control_wait_until': control_wait_until,
    'control_repeat_until': control_repeat_until,
    'control_stop': control_stop,

    # Events
    'event_whenflagclicked': event_whenflagclicked,
    'event_whenbroadcastreceived': event_whenbroadcastreceived,
    'event_broadcast': event_broadcast,
    'event_broadcastandwait': event_broadcastandwait,

    # Motion
    'motion_movesteps': motion_movesteps,
    'motion_gotoxy': motion_gotoxy,
    'motion_gox': motion_gox,
    'motion_goy': motion_goy,
    'motion_setx': motion_setx,
    'motion_sety': motion_sety,
    'motion_changexby': motion_changexby,
    'motion_changeyby': motion_changeyby,
    'motion_setdirection': motion_setdirection,
    'motion_pointindirection': motion_pointindirection,
    'motion_turnright': motion_turnright,
    'motion_turnleft': motion_turnleft,
    'motion_ifonedgebounce': motion_ifonedgebounce,
    'motion_setrotationstyle': motion_setrotationstyle,
    'motion_xposition': motion_xposition,
    'motion_yposition': motion_yposition,
    'motion_direction': motion_direction,
    'motion_glideto': motion_glideto,
    'motion_glidesecstoxy': motion_glideto,

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
    'data_insertatlist': data_insertatlist,
    'data_replaceitemoflist': data_replaceitemoflist,
    'data_itemoflist': data_itemoflist,
    'data_lengthoflist': data_lengthoflist,
    'data_listcontainsitem': data_listcontainsitem,

    # Sensing
    'sensing_touchingobject': sensing_touchingobject,
    'sensing_touchingcolor': sensing_touchingcolor,
    'sensing_keypressed': sensing_keypressed,
    'sensing_askandwait': sensing_askandwait,
    'sensing_resettimer': sensing_resettimer,
    'sensing_timer': sensing_timer,

    # Pen
    'pen_penDown': pen_penDown,
    'pen_penUp': pen_penUp,
    'pen_setPenColorToColor': pen_setPenColorToColor,
    'pen_changePenSizeBy': pen_changePenSizeBy,
    'pen_setPenSizeTo': pen_setPenSizeTo,
    'pen_clear': pen_clear,
    'pen_stamp': pen_stamp,

    # Procedures
    'procedures_def': procedures_def,
    'procedures_call': procedures_call,
}
