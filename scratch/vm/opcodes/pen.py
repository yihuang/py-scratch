"""
Pen opcodes — ``pen_penDown``, ``pen_penUp``, ``pen_stamp``, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target
    from ..types import Block

from ..constants import PEN_SIZE_MIN


def pen_pen_down(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.pen_down = True


def pen_pen_up(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.pen_down = False


def pen_set_pen_color_to_color(rt: Runtime, tgt: Target, block: Block) -> None:
    color = rt.val(tgt, block, "COLOR")
    if isinstance(color, (int, float)):
        color = int(color) & 0xFFFFFF
        red = (color >> 16) & 0xFF
        green = (color >> 8) & 0xFF
        blue = color & 0xFF
        tgt.pen_color = (red, green, blue)
    elif isinstance(color, str):
        color = color.strip().lstrip("#")
        if color.startswith("0x") or color.startswith("0X"):
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
    tgt.pen_size = max(PEN_SIZE_MIN, tgt.pen_size + rt.num(tgt, block, "SIZE"))


def pen_set_pen_size_to(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.pen_size = max(PEN_SIZE_MIN, rt.num(tgt, block, "SIZE"))


def pen_clear(rt: Runtime, tgt: Target, block: Block) -> None:
    """Clear pen layer. Handled by the renderer."""
    if rt.stage:
        rt.stage._pen_clear_requested = True


def pen_stamp(rt: Runtime, tgt: Target, block: Block) -> None:
    """Stamp the current costume onto the pen layer."""
    if rt.stage:
        if not hasattr(rt.stage, "_stamp_queue"):
            rt.stage._stamp_queue = []
        rt.stage._stamp_queue.append((tgt.x, tgt.y, tgt.size, tgt.direction, tgt.costume_index))
