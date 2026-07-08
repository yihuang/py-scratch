"""
Serialize data model → Scratch JSON format (.sb3 ``project.json``).

See ``docs/sb3-serialization.md`` for the full spec.
"""

from __future__ import annotations

from typing import Any

from ..vm.target import Target
from ..vm.types import Block, Costume, Field, Input, Sound
from ..vm.constants import (
    BLOCK_REF_FLAG,
    OBSOLETE_FLAG,
    PrimitiveType,
    SHADOW_FLAG,
    SERIALIZE_TEMPO,
    SERIALIZE_VIDEO_STATE,
    SERIALIZE_VIDEO_TRANSPARENCY,
)

# Scratch compact primitive type codes for shadow defaults
POSITIVE_NUMBER = 5


def serialize_block(block: Block) -> dict[str, Any]:
    """Convert a Block to Scratch JSON format."""
    obj: dict[str, Any] = {
        "opcode": block.opcode,
        "next": block.next,
        "parent": block.parent,
        "shadow": block.shadow,
        "topLevel": block.top_level,
    }
    if block.x is not None:
        obj["x"] = block.x
    if block.y is not None:
        obj["y"] = block.y
    if block.mutation is not None:
        obj["mutation"] = {
            "tagName": block.mutation.tag_name,
            "children": block.mutation.children,
            "proccode": block.mutation.proccode,
            "argumentids": block.mutation.argumentids,
            "argumentnames": block.mutation.argumentnames,
            "argumentdefaults": block.mutation.argumentdefaults,
            "warp": block.mutation.warp,
        }

    inputs: dict[str, list[Any]] = {}
    for name, inp in block.inputs.items():
        inputs[name] = serialize_input(inp)
    if inputs:
        obj["inputs"] = inputs
    else:
        obj["inputs"] = {}

    fields: dict[str, list[Any]] = {}
    for name, fld in block.fields.items():
        fields[name] = serialize_field(fld)
    if fields:
        obj["fields"] = fields
    else:
        obj["fields"] = {}

    return obj


def serialize_input(inp: Input) -> list[Any]:
    """Serialize an Input to Scratch ``[shadow_flag, value]`` format.

    * Variable references (``variable_name`` set) use OBSOLETE_FLAG (3) with a
      VARIABLE compact primitive ``[12, name, name]`` and a shadow default.
    * Literal values (``is_literal=True``) use SHADOW_FLAG (1) with a
      compact primitive ``[type_code, value]`` array.  Scratch stores ALL
      values as strings inside compact primitives, e.g. ``[4, "5"]``.
    * Block ID references use BLOCK_REF_FLAG (2).
    * Shadow inputs use SHADOW_FLAG (1) regardless.
    """
    if inp.variable_name is not None:
        flag = OBSOLETE_FLAG
        var_name = inp.variable_name
        # Variable ID resolved in ``_resolve_variable_inputs`` post-process.
        var_primitive = [PrimitiveType.VARIABLE, var_name, var_name]
        shadow_default = [POSITIVE_NUMBER, "1"]
        return [flag, var_primitive, shadow_default]

    if inp.shadow or inp.is_literal:
        flag = SHADOW_FLAG
        val = inp.value
        if isinstance(val, list) and len(val) >= 2 and isinstance(val[0], int):
            pass  # already a compact primitive — pass through
        elif inp.is_literal:
            if isinstance(val, str):
                val = [PrimitiveType.TEXT, val]
            elif isinstance(val, bool):
                val = [PrimitiveType.NUMBER, str(int(val))]
            elif isinstance(val, (int, float)):
                val = [PrimitiveType.NUMBER, str(val)]
            else:
                val = [PrimitiveType.TEXT, str(val) if val is not None else ""]
    else:
        flag = BLOCK_REF_FLAG
        val = inp.value
    return [flag, val]


def serialize_field(fld: Field) -> list[Any]:
    """Serialize a Field to Scratch ``[value, id]`` format."""
    return [fld.value, fld.id]


def serialize_costume(costume: Costume) -> dict[str, Any]:
    """Serialize a Costume to Scratch JSON format."""
    return {
        "name": costume.name,
        "dataFormat": costume.data_format,
        "bitmapResolution": costume.bitmap_resolution,
        "rotationCenterX": costume.rotation_center_x,
        "rotationCenterY": costume.rotation_center_y,
        "assetId": costume.asset_id,
        "md5ext": costume.md5ext,
    }


def serialize_sound(sound: Sound) -> dict[str, Any]:
    """Serialize a Sound to Scratch JSON format."""
    return {
        "name": sound.name,
        "dataFormat": sound.data_format,
        "rate": sound.rate,
        "sampleCount": sound.sample_count,
        "assetId": sound.asset_id,
        "md5ext": sound.md5ext,
    }


def serialize_target(target: Target) -> dict[str, Any]:
    """Serialize a Target to Scratch JSON format."""
    variables: dict[str, list[Any]] = {}
    for vid, var in target.variables.items():
        entry: list[Any] = [var.name, var.value]
        if var.is_cloud:
            entry.append(True)
        variables[vid] = entry

    lists: dict[str, list[Any]] = {}
    for lid, lst in target.lists.items():
        lists[lid] = [lst.name, list(lst.contents)]

    blocks: dict[str, dict[str, Any]] = {}
    for bid, block in target.blocks.items():
        blocks[bid] = serialize_block(block)

    data: dict[str, Any] = {
        "isStage": target.is_stage,
        "name": target.name,
        "variables": variables,
        "lists": lists,
        "broadcasts": {},
        "blocks": blocks,
        "currentCostume": target.costume_index,
        "costumes": [serialize_costume(c) for c in target.costumes],
        "sounds": [serialize_sound(s) for s in target.sounds],
        "volume": target.volume,
        "layerOrder": target.layer_order,
        "tempo": SERIALIZE_TEMPO,
        "videoTransparency": SERIALIZE_VIDEO_TRANSPARENCY,
        "videoState": SERIALIZE_VIDEO_STATE,
    }

    if not target.is_stage:
        data.update(
            {
                "x": target.x,
                "y": target.y,
                "direction": target.direction,
                "size": target.size,
                "visible": target.visible,
                "rotationStyle": target.rotation_style,
                "draggable": target.draggable,
            }
        )

    return data


def build_project_json(runtime: Any) -> dict[str, Any]:
    """Build the full project.json dict from a Runtime."""
    # Build combined variable name→ID map across all targets
    all_var_names: dict[str, str] = {}
    for tgt in runtime.targets:
        for vid, var in tgt.variables.items():
            all_var_names[var.name] = vid

    targets_json = [serialize_target(t) for t in runtime.targets]

    # Resolve variable IDs in inlined variable references across all targets.
    # Stage variables referenced by sprites need the stage's variable ID.
    for tgt_json in targets_json:
        for blk in tgt_json.get("blocks", {}).values():
            for inp in blk.get("inputs", {}).values():
                if isinstance(inp, list) and len(inp) >= 2 and inp[0] == OBSOLETE_FLAG:
                    var_part = inp[1]
                    if (
                        isinstance(var_part, list)
                        and len(var_part) >= 3
                        and var_part[0] == PrimitiveType.VARIABLE
                    ):
                        var_name = var_part[1]
                        vid = all_var_names.get(var_name)
                        if vid:
                            var_part[2] = vid

    return {
        "targets": targets_json,
        "monitors": [],
        "extensions": [],
        "meta": {
            "semver": "3.0.0",
            "vm": "0.2.0",
            "agent": "py-scratch",
        },
    }
