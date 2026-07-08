"""
Looks opcodes — ``looks_switchcostumeto``, ``looks_say``, ``looks_hide``, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target
    from ..types import Block

from ..thread import Wait
from ..constants import LOOKS_NEXTCOSTUME_OFFSET
from ._helpers import (
    _format_bubble_text,
    _set_backdrop,
    _set_costume,
)


def looks_switchcostumeto(rt: Runtime, tgt: Target, block: Block) -> None:
    val = rt.val(tgt, block, "COSTUME")
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
    choice = rt.field(tgt, block, "FRONT_BACK") or "front"
    if choice == "front":
        max_layer = max((o.layer_order for o in rt.sprite_targets()), default=0)
        tgt.layer_order = max_layer + 1
    else:
        min_layer = min((o.layer_order for o in rt.sprite_targets()), default=0)
        tgt.layer_order = min_layer - 1


def looks_hideallsprites(rt: Runtime, tgt: Target, block: Block) -> None:
    """Legacy no-op."""


def looks_changestretchby(rt: Runtime, tgt: Target, block: Block) -> None:
    """Legacy no-op."""


def looks_setstretchto(rt: Runtime, tgt: Target, block: Block) -> None:
    """Legacy no-op."""


def looks_goforwardbackwardlayers(rt: Runtime, tgt: Target, block: Block) -> None:
    if tgt.is_stage:
        return
    num = rt.num_int(tgt, block, "NUM")
    if rt.field(tgt, block, "FORWARD_BACKWARD") == "backward":
        num = -num
    tgt.layer_order += num


def looks_setsizeto(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.size = rt.num(tgt, block, "SIZE")


def looks_changesizeby(rt: Runtime, tgt: Target, block: Block) -> None:
    tgt.size += rt.num(tgt, block, "CHANGE")


def looks_costumenumbername(rt: Runtime, tgt: Target, block: Block) -> Any:
    if rt.field(tgt, block, "NUMBER_NAME") == "number":
        return tgt.costume_index + 1
    else:
        return tgt.current_costume_name


def looks_costume(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Menu block: costume dropdown for ``looks_switchcostumeto``."""
    return rt.field(tgt, block, "COSTUME")


def looks_backdrops(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Menu block: backdrop dropdown for ``looks_switchbackdropto``."""
    return rt.field(tgt, block, "BACKDROP")


def looks_backdropnumbername(rt: Runtime, tgt: Target, block: Block) -> Any:
    if rt.field(tgt, block, "NUMBER_NAME") == "number":
        return tgt.costume_index + 1
    else:
        return tgt.current_costume_name


def looks_switchbackdropto(rt: Runtime, tgt: Target, block: Block) -> None:
    """Switch backdrop (on the stage, not the sprite)."""
    if rt.stage is None:
        return
    val = rt.val(tgt, block, "BACKDROP")
    _set_backdrop(rt, val)


def looks_switchbackdroptoandwait(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Switch backdrop and wait for all backdrop-switch handlers to finish."""
    if rt.stage is None:
        return
    val = rt.val(tgt, block, "BACKDROP")
    started = _set_backdrop(rt, val)
    while any(th for th in started if th.status != "done" and th in rt.threads):
        yield Wait(0.1)


def looks_say(rt: Runtime, tgt: Target, block: Block) -> None:
    msg = rt.val(tgt, block, "MESSAGE")
    tgt.say_text = _format_bubble_text(msg) or None


def looks_sayforsecs(rt: Runtime, tgt: Target, block: Block) -> Any:
    msg = rt.val(tgt, block, "MESSAGE")
    secs = rt.num(tgt, block, "SECS")
    tgt.say_text = _format_bubble_text(msg) or None
    if secs > 0:
        yield Wait(secs)
    tgt.say_text = None


def looks_think(rt: Runtime, tgt: Target, block: Block) -> None:
    """Think bubble."""
    msg = rt.val(tgt, block, "MESSAGE")
    tgt.say_text = _format_bubble_text(msg) or None


def looks_thinkforsecs(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Think bubble for a duration."""
    msg = rt.val(tgt, block, "MESSAGE")
    secs = rt.num(tgt, block, "SECS")
    tgt.say_text = _format_bubble_text(msg) or None
    if secs > 0:
        yield Wait(secs)
    tgt.say_text = None


def looks_nextbackdrop(rt: Runtime, tgt: Target, block: Block) -> None:
    """Switch to next backdrop on stage."""
    if rt.stage:
        n = len(rt.stage.costumes)
        if n > 0:
            rt.stage.costume_index = (rt.stage.costume_index + 1) % n


def looks_changeeffectby(rt: Runtime, tgt: Target, block: Block) -> None:
    effect = rt.field(tgt, block, "EFFECT")
    change = rt.num(tgt, block, "CHANGE")
    if effect:
        val = tgt.effects.get(effect, 0) + change
        if effect == "ghost":
            val = max(0, min(100, val))
        elif effect == "brightness":
            val = max(-100, min(100, val))
        tgt.effects[effect] = val


def looks_seteffectto(rt: Runtime, tgt: Target, block: Block) -> None:
    effect = rt.field(tgt, block, "EFFECT")
    value = rt.num(tgt, block, "VALUE")
    if effect:
        if effect == "ghost":
            value = max(0, min(100, value))
        elif effect == "brightness":
            value = max(-100, min(100, value))
        tgt.effects[effect] = value


def looks_cleargraphiceffects(rt: Runtime, tgt: Target, block: Block) -> None:
    for k in tgt.effects:
        tgt.effects[k] = 0


def looks_size(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Reporter: current sprite size."""
    return tgt.size
