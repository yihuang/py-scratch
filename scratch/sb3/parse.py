"""
Parse Scratch JSON format → data model (.sb3 ``project.json``).

See ``docs/sb3-serialization.md`` for the full spec.
"""

from __future__ import annotations

import logging
from typing import Any

from ..vm.target import BroadcastMsg, ListVar, Target, Variable
from ..vm.types import Block, Costume, Field, Input, Mutation, Sound
from ..vm.constants import (
    OBSOLETE_FLAG,
    PrimitiveType,
    SHADOW_FLAG,
)


logger = logging.getLogger(__name__)


# Opcodes/field names for literal primitive types (4–10).
_LITERAL_PRIMITIVES: dict[PrimitiveType, tuple[str, str]] = {
    PrimitiveType.NUMBER: ('math_number', 'NUM'),
    PrimitiveType.POSITIVE_NUMBER: ('math_positive_number', 'NUM'),
    PrimitiveType.WHOLE_NUMBER: ('math_whole_number', 'NUM'),
    PrimitiveType.INTEGER: ('math_integer', 'NUM'),
    PrimitiveType.ANGLE: ('math_angle', 'NUM'),
    PrimitiveType.COLOR_PICKER: ('colour_picker', 'COLOUR'),
    PrimitiveType.TEXT: ('text', 'TEXT'),
}


def parse_target(data: dict[str, Any]) -> Target:
    """Convert a single target dict into a Target instance."""
    target = Target(
        name=data.get('name', 'Sprite'),
        is_stage=data.get('isStage', False),
        x=data.get('x', 0),
        y=data.get('y', 0),
        _direction=data.get('direction', 90),
        size=data.get('size', 100),
        visible=data.get('visible', True),
        volume=data.get('volume', 100),
        layer_order=data.get('layerOrder', 0),
        costume_index=data.get('currentCostume', 0),
        rotation_style=data.get('rotationStyle', 'all around'),
        draggable=data.get('draggable', False),
    )

    # Variables  {id: [name, value]}
    for var_id, var_data in data.get('variables', {}).items():
        name = var_data[0]
        value = var_data[1]
        is_cloud = len(var_data) > 2 and var_data[2]
        target.variables[var_id] = Variable(name=name, value=value, is_cloud=is_cloud)

    # Lists  {id: [name, [items...]]}
    for list_id, list_data in data.get('lists', {}).items():
        name = list_data[0]
        items = list(list_data[1]) if len(list_data) > 1 else []
        target.lists[list_id] = ListVar(name=name, contents=items)

    # Broadcasts (messages)
    for msg_id, msg_data in data.get('broadcasts', {}).items():
        name = msg_data if isinstance(msg_data, str) else msg_data[0]
        target.broadcasts[msg_id] = BroadcastMsg(name)

    # Costumes
    for c_data in data.get('costumes', []):
        target.costumes.append(parse_costume(c_data))

    # Sounds
    for s_data in data.get('sounds', []):
        target.sounds.append(parse_sound(s_data))

    # Blocks
    for block_id, block_data in data.get('blocks', {}).items():
        if isinstance(block_data, list):
            target.blocks[block_id] = parse_primitive_block(block_id, block_data)
        else:
            target.blocks[block_id] = parse_block(block_id, block_data)

    return target


def parse_block(block_id: str, data: dict[str, Any]) -> Block:
    """Convert a single block dict into a Block instance."""
    inputs: dict[str, Input] = {}
    for name, inp_data in data.get('inputs', {}).items():
        inputs[name] = parse_input(inp_data)

    fields: dict[str, Field] = {}
    for name, fld_data in data.get('fields', {}).items():
        fields[name] = parse_field(name, fld_data)

    return Block(
        id=block_id,
        opcode=data.get('opcode', ''),
        next=data.get('next'),
        parent=data.get('parent'),
        inputs=inputs,
        fields=fields,
        shadow=data.get('shadow', False),
        top_level=data.get('topLevel', False),
        x=data.get('x'),
        y=data.get('y'),
        mutation=parse_mutation(data.get('mutation')),
    )


def parse_primitive_block(block_id: str, data: list[Any]) -> Block:
    """Expand an inlined primitive array into a full :class:`Block`."""
    type_code = data[0] if data else 0
    try:
        ptype = PrimitiveType(type_code)
    except ValueError:
        logger.warning('Unknown primitive type %r in block %r; skipping', type_code, block_id)
        return Block(id=block_id, opcode='', shadow=True)

    fields: dict[str, Field] = {}
    top_level = False
    x: Any = None
    y: Any = None

    if ptype is PrimitiveType.BROADCAST:
        opcode = 'event_broadcast_menu'
        fields['BROADCAST_OPTION'] = Field(
            value=data[1] if len(data) > 1 else '',
            id=data[2] if len(data) > 2 else None,
            variable_type='broadcast_msg',
        )
    elif ptype is PrimitiveType.VARIABLE:
        opcode = 'data_variable'
        fields['VARIABLE'] = Field(
            value=data[1] if len(data) > 1 else '',
            id=data[2] if len(data) > 2 else None,
            variable_type='',
        )
        if len(data) > 3:
            top_level, x, y = True, data[3], data[4]
    elif ptype is PrimitiveType.LIST:
        opcode = 'data_listcontents'
        fields['LIST'] = Field(
            value=data[1] if len(data) > 1 else '',
            id=data[2] if len(data) > 2 else None,
            variable_type='list',
        )
        if len(data) > 3:
            top_level, x, y = True, data[3], data[4]
    else:
        opcode, field_name = _LITERAL_PRIMITIVES[ptype]
        fields[field_name] = Field(value=data[1] if len(data) > 1 else None)

    return Block(
        id=block_id,
        opcode=opcode,
        inputs={},
        fields=fields,
        shadow=False,
        top_level=top_level,
        x=x,
        y=y,
    )


def parse_input(data: list[Any]) -> Input:
    """Parse a block input array ``[shadow_flag, value, ...]``.

    See ``docs/sb3-serialization.md`` for the format spec.
    """
    shadow_flag = data[0] if len(data) > 0 else 0
    is_shadow = shadow_flag in (SHADOW_FLAG, OBSOLETE_FLAG)

    if shadow_flag == OBSOLETE_FLAG and len(data) >= 3:
        # [3, block_id, shadow] — take the block reference (data[1]) as value
        value = data[1]
    else:
        value = data[1] if len(data) > 1 else None

    # Normalize bare literals to compact primitives
    if shadow_flag == SHADOW_FLAG and not isinstance(value, (list, tuple)):
        if isinstance(value, str):
            value = [PrimitiveType.TEXT, value]
        elif isinstance(value, bool):
            value = [PrimitiveType.NUMBER, int(value)]
        elif isinstance(value, (int, float)):
            value = [PrimitiveType.NUMBER, value]

    return Input(value=value, shadow=is_shadow)


def parse_mutation(data: dict[str, Any] | None) -> Mutation | None:
    """Parse the mutation dict from a block, or ``None`` if absent."""
    if not data or not isinstance(data, dict):
        return None
    return Mutation(
        tag_name=data.get('tagName', 'mutation'),
        children=data.get('children', []),
        proccode=data.get('proccode', ''),
        argumentids=data.get('argumentids', '[]'),
        argumentnames=data.get('argumentnames', '[]'),
        argumentdefaults=data.get('argumentdefaults', '[]'),
        warp=data.get('warp', 'false'),
    )


def parse_field(name: str, data: list[Any]) -> Field:
    """Parse a field array ``[value, id_or_none]``."""
    value = data[0] if len(data) > 0 else ''
    field_id = data[1] if len(data) > 1 else None

    if name == 'BROADCAST_OPTION':
        var_type = 'broadcast_msg'
    elif name == 'VARIABLE':
        var_type = ''
    elif name == 'LIST':
        var_type = 'list'
    else:
        var_type = None

    return Field(value=value, id=field_id, variable_type=var_type)


def parse_costume(data: dict[str, Any]) -> Costume:
    """Parse a costume dict."""
    return Costume(
        name=data.get('name', ''),
        data_format=data.get('dataFormat', ''),
        bitmap_resolution=data.get('bitmapResolution', 1),
        rotation_center_x=data.get('rotationCenterX', 0.0),
        rotation_center_y=data.get('rotationCenterY', 0.0),
        asset_id=data.get('assetId', ''),
        md5ext=data.get('md5ext', ''),
    )


def parse_sound(data: dict[str, Any]) -> Sound:
    """Parse a sound dict."""
    return Sound(
        name=data.get('name', ''),
        data_format=data.get('dataFormat', ''),
        rate=data.get('rate', 0),
        sample_count=data.get('sampleCount', 0),
        asset_id=data.get('assetId', ''),
        md5ext=data.get('md5ext', ''),
    )
