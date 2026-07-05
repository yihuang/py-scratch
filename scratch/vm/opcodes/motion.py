"""
Motion opcodes — ``motion_movesteps``, ``motion_goto``, etc.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target
    from ..types import Block

from ..thread import YIELD
from ..constants import SCRATCH_RIGHT, STAGE_RIGHT, STAGE_TOP
from ._helpers import _field_val, _str, _target_xy


def motion_movesteps(rt: Runtime, tgt: Target, block: Block) -> None:
    steps = rt.num(tgt, block, 'STEPS')
    rad = math.radians(SCRATCH_RIGHT - tgt.direction)
    tgt.set_xy(tgt.x + steps * math.cos(rad), tgt.y + steps * math.sin(rad))


def motion_goto(rt: Runtime, tgt: Target, block: Block) -> None:
    target_name = _field_val(block.fields.get('TO'))
    if not target_name:
        target_name = _str(rt.val(tgt, block, 'TO'))
    xy = _target_xy(rt, target_name)
    if xy is not None:
        tgt.set_xy(xy[0], xy[1])


def motion_gotoxy(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.set_xy(rt.num(tgt, block, 'X'), rt.num(tgt, block, 'Y'))


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
    target_name = _field_val(block.fields.get('TOWARDS'))
    if not target_name:
        target_name = _str(rt.val(tgt, block, 'TOWARDS'))
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
    """Bounce off stage edges, matching official Scratch behaviour."""
    bounds = tgt.scratch_bounds()
    if bounds == (0, 0, 0, 0):
        return

    left, top, right, bottom = bounds
    world_left = tgt.x + left
    world_top = tgt.y + top
    world_right = tgt.x + right
    world_bottom = tgt.y + bottom

    dist_left = max(0.0, world_left + STAGE_RIGHT)
    dist_top = max(0.0, STAGE_TOP - world_top)
    dist_right = max(0.0, STAGE_RIGHT - world_right)
    dist_bottom = max(0.0, world_bottom + STAGE_TOP)

    nearest_edge = ''
    min_dist = float('inf')
    for edge, d in [
        ('left', dist_left),
        ('top', dist_top),
        ('right', dist_right),
        ('bottom', dist_bottom),
    ]:
        if d < min_dist:
            min_dist = d
            nearest_edge = edge

    if min_dist > 0:
        return

    radians = math.radians(90 - tgt.direction)
    dx = math.cos(radians)
    dy = -math.sin(radians)

    if nearest_edge == 'left':
        dx = max(0.2, abs(dx))
    elif nearest_edge == 'top':
        dy = max(0.2, abs(dy))
    elif nearest_edge == 'right':
        dx = 0 - max(0.2, abs(dx))
    elif nearest_edge == 'bottom':
        dy = 0 - max(0.2, abs(dy))

    new_direction = math.degrees(math.atan2(dy, dx)) + 90
    tgt.direction = new_direction


def motion_setrotationstyle(rt: Runtime, tgt: Target, block: Block) -> None:
    style = block.fields.get('STYLE')
    if style:
        tgt.rotation_style = style.value


def motion_xposition(rt: Runtime, tgt: Target, block: Block) -> Any:
    val = tgt.x
    if abs(val - round(val)) < 1e-9:
        val = round(val)
    return val


def motion_yposition(rt: Runtime, tgt: Target, block: Block) -> Any:
    val = tgt.y
    if abs(val - round(val)) < 1e-9:
        val = round(val)
    return val


def motion_direction(rt: Runtime, tgt: Target, block: Block) -> Any:
    return tgt.direction


def motion_glidesecstoxy(rt: Runtime, tgt: Target, block: Block) -> Any:
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


def motion_glideto(rt: Runtime, tgt: Target, block: Block) -> Any:
    secs = rt.num(tgt, block, 'SECS')
    target_name = _field_val(block.fields.get('TO'))
    if not target_name:
        target_name = _str(rt.val(tgt, block, 'TO'))
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


# Legacy no-op motion blocks


def motion_scroll_right(rt: Runtime, tgt: Target, block: Block) -> None:
    pass


def motion_scroll_up(rt: Runtime, tgt: Target, block: Block) -> None:
    pass


def motion_align_scene(rt: Runtime, tgt: Target, block: Block) -> None:
    pass


def motion_xscroll(rt: Runtime, tgt: Target, block: Block) -> Any:
    return 0


def motion_yscroll(rt: Runtime, tgt: Target, block: Block) -> Any:
    return 0
