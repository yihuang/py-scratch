"""
Event opcodes — ``event_whenflagclicked``, ``event_broadcast``, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target
    from ..types import Block

from ..thread import YIELD
from . import _field_val


def event_whenflagclicked(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — the scheduler starts the next block directly."""


def event_whenbroadcastreceived(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by broadcast."""


def event_whenkeypressed(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by key press."""


def event_whenthisspriteclicked(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by sprite click."""


def event_whenstageclicked(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by stage click."""


def event_whenbackdropswitchesto(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hat — triggered by backdrop switch."""


def event_whentouchingobject(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Edge-activated hat — returns True when touching the specified object."""
    obj = block.fields.get('TOUCHINGOBJECTMENU')
    obj_name = _field_val(obj) if obj else ''
    if obj_name == '':
        return False
    from . import _touching_object_check  # noqa: PLC0415

    touching = _touching_object_check(rt, tgt, obj_name)
    return rt._check_edge_hat('event_whentouchingobject', tgt, block, touching)


def event_whengreaterthan(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Edge-activated hat — returns True when timer/loudness > VALUE."""
    option = block.fields.get('WHENGREATERTHANMENU')
    opt = _field_val(option) if option else ''
    value = rt.num(tgt, block, 'VALUE')
    if opt == 'timer':
        result = rt.clock.now() > value
    elif opt == 'loudness':
        result = False
    else:
        result = False
    return rt._check_edge_hat('event_whengreaterthan', tgt, block, result)


def event_broadcast(rt: Runtime, tgt: Target, block: Block) -> None:
    rt.broadcast(rt.val(tgt, block, 'BROADCAST_INPUT'))


def event_broadcastandwait(rt: Runtime, tgt: Target, block: Block) -> Any:
    started = rt.broadcast(rt.val(tgt, block, 'BROADCAST_INPUT'))
    while any(th for th in started if not th.is_done()):
        yield YIELD
