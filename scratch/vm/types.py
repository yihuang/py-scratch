"""
Core data model for Scratch blocks, inputs, fields, costumes, and sounds.
Mirrors the Scratch 3.0 JSON project format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid

# ── Block Inputs & Fields ────────────────────────────────────────────────


@dataclass
class Field:
    """A dropdown/field on a block (e.g. variable name, operator choice)."""

    value: Any
    variable_type: str | None = None  # '' for broadcast, 'list' for list var
    id: str | None = None


@dataclass
class Input:
    """An input slot on a block.

    ``value`` is one of:
    * a literal (int, float, str, bool) — a primitive value;
    * a ``Block`` id string — a reference to another block tree;
    * an ``[id, value]`` shadow pair — an obsolete/backward-compat form.
    """

    value: Any
    shadow: bool = False  # whether the block in this slot is a shadow
    is_literal: bool = False  # True when value is a literal, not a block ID


# ── Mutation (for procedures / custom blocks) ────────────────────────────


@dataclass
class Mutation:
    """Metadata for procedure definitions/calls."""

    tag_name: str = 'mutation'
    children: list[Any] = field(default_factory=list)
    proccode: str = ''
    argumentids: str = '[]'
    argumentnames: str = '[]'
    argumentdefaults: str = '[]'
    warp: str = 'false'  # 'true' = run without screen refresh
    prototype: str | None = None  # block id of the prototype


# ── Block ────────────────────────────────────────────────────────────────


@dataclass
class Block:
    """A single Scratch block node.

    Blocks form a linked list via ``next`` and point back via ``parent``.
    Inputs reference child blocks (reporters, sub-stacks).
    """

    id: str
    opcode: str
    next: str | None = None  # next block in the stack
    parent: str | None = None  # block that contains this one
    inputs: dict[str, Input] = field(default_factory=dict)
    fields: dict[str, Field] = field(default_factory=dict)
    shadow: bool = False
    top_level: bool = False
    mutation: Mutation | None = None
    x: float | None = None  # editor position (top_level only)
    y: float | None = None

# ── Costume & Sound ──────────────────────────────────────────────────────


@dataclass
class Costume:
    """A costume (image) or backdrop belonging to a target."""

    name: str
    data_format: str = ''  # 'svg', 'png', 'jpg', 'bmp', 'gif'
    bitmap_resolution: int = 1
    rotation_center_x: float = 0.0
    rotation_center_y: float = 0.0
    asset_id: str = ''  # Scratch assetId (SHA1 hex)
    md5ext: str = ''  # filename inside .sb3, e.g. 'abc.svg'
    data: bytes = b''  # raw image bytes from the .sb3 archive
    surface: Any = None  # pygame.Surface | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Costume:
        return cls(
            name=data.get('name', ''),
            data_format=data.get('dataFormat', ''),
            bitmap_resolution=data.get('bitmapResolution', 1),
            rotation_center_x=data.get('rotationCenterX', 0.0),
            rotation_center_y=data.get('rotationCenterY', 0.0),
        )


@dataclass
class Sound:
    """A sound asset."""

    name: str
    data_format: str = ''  # 'wav', 'mp3', etc.
    rate: int = 0
    sample_count: int = 0
    asset_id: str = ''  # Scratch assetId
    md5ext: str = ''  # filename inside .sb3
    data: bytes = b''
    sound: Any = None  # pygame.mixer.Sound | None


# ── Convenience builders ─────────────────────────────────────────────────


def make_block(
    opcode: str,
    block_id: str | None = None,
    inputs: dict[str, Input | Any] | None = None,
    fields: dict[str, Field | Any] | None = None,
    next_: str | None = None,
    parent: str | None = None,
    top_level: bool = False,
    mutation: Mutation | None = None,
) -> Block:
    """Construct a Block from simplified arguments.

    Inputs are given as ``{name: value}`` — literals or sub-block ids.
    Fields as ``{name: value}`` (plain values, not Field objects).
    """

    bid = block_id or str(uuid.uuid4())[:8]
    parsed_inputs: dict[str, Input] = {}
    if inputs:
        for name, val in inputs.items():
            if isinstance(val, Input):
                parsed_inputs[name] = val
            else:
                parsed_inputs[name] = Input(value=val)
    parsed_fields: dict[str, Field] = {}
    if fields:
        for name, val in fields.items():
            if isinstance(val, Field):
                parsed_fields[name] = val
            else:
                parsed_fields[name] = Field(value=val)
    return Block(
        id=bid,
        opcode=opcode,
        inputs=parsed_inputs,
        fields=parsed_fields,
        next=next_,
        parent=parent,
        top_level=top_level,
        mutation=mutation,
    )
