"""
Sensing opcodes — ``sensing_touchingobject``, ``sensing_keypressed``, etc.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target
    from ..types import Block, Input

from ..constants import (
    DISTANCE_UNREACHABLE,
    DST_OFFSET_SECS,
    SECONDS_PER_DAY,
    YEAR_2000_EPOCH,
)
from ..thread import YIELD
from ._helpers import _field_val, _str, _touching_object_check


def sensing_touchingobject(rt: Runtime, tgt: Target, block: Block) -> Any:
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
    return _touching_object_check(rt, tgt, obj_name)


def sensing_touchingcolor(rt: Runtime, tgt: Target, block: Block) -> Any:
    return False  # simplified


def sensing_keypressed(rt: Runtime, tgt: Target, block: Block) -> Any:
    key_name = _field_val(block.fields.get('KEY_OPTION'))
    return rt.is_key_pressed(key_name)


def sensing_askandwait(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Ask a question and wait for an answer."""
    question = _str(rt.val(tgt, block, 'QUESTION'))
    tgt.say_text = question or None
    rt.set_answer(None)
    while rt.answer is None:
        yield YIELD
    tgt.say_text = None


def sensing_answer(rt: Runtime, tgt: Target, block: Block) -> Any:
    return '' if rt.answer is None else rt.answer


def sensing_resettimer(rt: Runtime, tgt: Target, block: Block) -> None:
    rt.clock.reset()


def sensing_timer(rt: Runtime, tgt: Target, block: Block) -> Any:
    return rt.clock.now()


def sensing_coloristouchingcolor(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Color touching color (simplified: no-op)."""
    return False


def sensing_distanceto(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Distance to _mouse_ or another sprite."""
    dest = block.fields.get('DISTANCETOMENU')
    dest_name = _field_val(dest) if dest else '_mouse_'
    if dest_name == '_mouse_':
        dx = tgt.x - rt.mouse_x()
        dy = tgt.y - rt.mouse_y()
        return math.sqrt(dx * dx + dy * dy)
    other = rt.get_target_by_name(dest_name)
    if other:
        dx = tgt.x - other.x
        dy = tgt.y - other.y
        return math.sqrt(dx * dx + dy * dy)
    else:
        return DISTANCE_UNREACHABLE


def sensing_of(rt: Runtime, tgt: Target, block: Block) -> Any:
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
            return obj.x
        case 'y' | 'y position':
            return obj.y
        case 'direction':
            return obj.direction
        case 'costume #' | 'costume':
            return obj.costume_index + 1
        case 'costume name':
            return obj.current_costume_name
        case 'size':
            return obj.size
        case 'volume':
            return obj.volume
        case 'backdrop name':
            return obj.current_costume_name if obj.is_stage else ''
        case 'backdrop #' | 'background #':
            return (obj.costume_index + 1) if obj.is_stage else 0
        case _:
            var = obj.lookup_variable(prop_name)
            return var.value if var else 0


def sensing_mousex(rt: Runtime, tgt: Target, block: Block) -> Any:
    return rt.mouse_x()


def sensing_mousey(rt: Runtime, tgt: Target, block: Block) -> Any:
    return rt.mouse_y()


def sensing_setdragmode(rt: Runtime, tgt: Target, block: Block) -> None:
    drag = block.fields.get('DRAG_MODE')
    if drag:
        tgt.draggable = _field_val(drag) == 'draggable'


def sensing_mousedown(rt: Runtime, tgt: Target, block: Block) -> Any:
    return rt.mouse_down()


def sensing_current(rt: Runtime, tgt: Target, block: Block) -> Any:
    lt = time.localtime()
    menu = block.fields.get('CURRENTMENU')
    opt = _field_val(menu) if menu else ''
    match opt:
        case 'YEAR':
            return lt.tm_year
        case 'MONTH':
            return lt.tm_mon
        case 'DATE':
            return lt.tm_mday
        case 'DAYOFWEEK':
            return (lt.tm_wday + 1) % 7 + 1
        case 'HOUR':
            return lt.tm_hour
        case 'MINUTE':
            return lt.tm_min
        case 'SECOND':
            return lt.tm_sec
        case _:
            return 0


def sensing_dayssince2000(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Days since 2000-01-01 (Scratch-compatible)."""
    epoch = time.mktime(YEAR_2000_EPOCH)
    now = time.time()
    is_dst = time.localtime(now).tm_isdst
    offset = time.timezone
    if is_dst > 0:
        offset -= DST_OFFSET_SECS
    return (now - epoch + offset) / SECONDS_PER_DAY


def sensing_loudness(rt: Runtime, tgt: Target, block: Block) -> Any:
    return 0


def sensing_loud(rt: Runtime, tgt: Target, block: Block) -> Any:
    return False


def sensing_online(rt: Runtime, tgt: Target, block: Block) -> Any:
    return True


def sensing_username(rt: Runtime, tgt: Target, block: Block) -> Any:
    return 'Scratcher'


def sensing_userid(rt: Runtime, tgt: Target, block: Block) -> Any:
    return ''
