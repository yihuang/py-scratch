"""
sb3 — load and unpack Scratch 3.0 project files (.sb3).

An .sb3 file is a ZIP archive containing ``project.json`` and asset
files (costume images, sounds).  This module parses the JSON into
our data model and loads assets as pygame surfaces.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

import pygame

from ..vm.runtime import Runtime
from ..vm.target import BroadcastMsg, ListVar, Target, Variable
from ..vm.types import Block, Costume, Field, Input, Sound

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  Top-level loader
# ═══════════════════════════════════════════════════════════════════════


def load_project(path: str | Path | io.IOBase) -> Runtime:
    """Load an .sb3 file and return a configured Runtime."""
    if isinstance(path, (str, Path)):
        path = Path(path)
        if not path.suffix == '.sb3':
            msg = f'Expected .sb3 file, got {path.suffix}'
            raise ValueError(msg)
        with zipfile.ZipFile(path) as zf:
            data = json.loads(zf.read('project.json'))
    else:
        data = _read_json_from_stream(path)
    return _from_json(data, path if isinstance(path, Path) else Path())


def _read_json_from_stream(stream: io.IOBase) -> dict[str, Any]:
    buf = io.BytesIO(stream.read())
    with zipfile.ZipFile(buf) as zf:
        return json.loads(zf.read('project.json'))  # type: ignore[no-any-return]


# ═══════════════════════════════════════════════════════════════════════
#  JSON → data model
# ═══════════════════════════════════════════════════════════════════════


def _from_json(data: dict[str, Any], source_path: Path) -> Runtime:
    """Convert parsed project.json into a populated Runtime."""
    rt = Runtime()

    for target_data in data.get('targets', []):
        target = _parse_target(target_data)
        rt.add_target(target)

    return rt


def _parse_target(data: dict[str, Any]) -> Target:
    """Convert a single target dict into a Target instance."""
    target = Target(
        name=data.get('name', 'Sprite'),
        is_stage=data.get('isStage', False),
        x=data.get('x', 0),
        y=data.get('y', 0),
        direction=data.get('direction', 90),
        size=data.get('size', 100),
        visible=data.get('visible', True),
        volume=data.get('volume', 100),
        layer_order=data.get('layerOrder', 0),
        current_costume=data.get('currentCostume', 0),
        rotation_style=data.get('rotationStyle', 'all around'),
        draggable=data.get('draggable', False),
    )
    target.costume_index = target.current_costume

    # Variables  {id: [name, value]}
    for var_id, var_data in data.get('variables', {}).items():
        name = var_data[0]
        value = var_data[1]
        is_cloud = len(var_data) > 2 and var_data[2]
        target.variables[var_id] = Variable(
            name=name,
            value=value,
            is_cloud=is_cloud,
        )

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
        target.costumes.append(_parse_costume(c_data))

    # Sounds
    for s_data in data.get('sounds', []):
        target.sounds.append(_parse_sound(s_data))

    # Blocks
    for block_id, block_data in data.get('blocks', {}).items():
        target.blocks[block_id] = _parse_block(block_id, block_data)

    return target


# ═══════════════════════════════════════════════════════════════════════
#  Block parsing
# ═══════════════════════════════════════════════════════════════════════


def _parse_block(block_id: str, data: dict[str, Any]) -> Block:
    """Convert a single block dict into a Block instance."""
    inputs: dict[str, Input] = {}
    for name, inp_data in data.get('inputs', {}).items():
        inputs[name] = _parse_input(inp_data)

    fields: dict[str, Field] = {}
    for name, fld_data in data.get('fields', {}).items():
        fields[name] = _parse_field(fld_data)

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
    )


def _parse_input(data: list[Any]) -> Input:
    """Parse a block input array ``[shadow_flag, value, ...]``.

    Scratch 3.0 input format:
        [1, literal]           — shadow with literal value
        [2, block_id]          — reference to another block
        [3, value, block_id]   — obsolete shadow+block pair (value is
                                 the shadow's default)
    """
    shadow_flag = data[0] if len(data) > 0 else 0
    value = data[1] if len(data) > 1 else None
    is_shadow = shadow_flag in (1, 3)

    name = ''  # Inputs in this context don't have internal names
    inp = Input(name=name, value=value, shadow=is_shadow)
    return inp


def _parse_field(data: list[Any]) -> Field:
    """Parse a field array ``[value, id_or_none]``."""
    value = data[0] if len(data) > 0 else ''
    field_id = data[1] if len(data) > 1 else None
    var_type = None

    # Field id carries type info when it's a reference
    if field_id is not None:
        if isinstance(field_id, str) and field_id.startswith('_'):
            var_type = field_id
        else:
            var_type = ''  # variable reference

    return Field(name='', value=value, id=field_id, variable_type=var_type)


# ═══════════════════════════════════════════════════════════════════════
#  Costume & Sound
# ═══════════════════════════════════════════════════════════════════════


def _parse_costume(data: dict[str, Any]) -> Costume:
    return Costume(
        name=data.get('name', ''),
        data_format=data.get('dataFormat', ''),
        bitmap_resolution=data.get('bitmapResolution', 1),
        rotation_center_x=data.get('rotationCenterX', 0.0),
        rotation_center_y=data.get('rotationCenterY', 0.0),
        asset_id=data.get('assetId', ''),
        md5ext=data.get('md5ext', ''),
    )


def _parse_sound(data: dict[str, Any]) -> Sound:
    return Sound(
        name=data.get('name', ''),
        data_format=data.get('dataFormat', ''),
        rate=data.get('rate', 0),
        sample_count=data.get('sampleCount', 0),
        asset_id=data.get('assetId', ''),
        md5ext=data.get('md5ext', ''),
    )


# ═══════════════════════════════════════════════════════════════════════
#  Asset loading
# ═══════════════════════════════════════════════════════════════════════


def load_assets(
    runtime: Runtime,
    source_path: str | Path | io.IOBase,
    asset_dir: str | Path | None = None,
) -> None:
    if isinstance(source_path, (str, Path)):
        with zipfile.ZipFile(Path(source_path)) as zf:
            _load_costumes(runtime, zf, asset_dir)
            _load_sounds(runtime, zf, asset_dir)
    else:
        buf = io.BytesIO(source_path.read())
        with zipfile.ZipFile(buf) as zf:
            _load_costumes(runtime, zf, asset_dir)
            _load_sounds(runtime, zf, asset_dir)


def _load_costumes(runtime: Runtime, zf: zipfile.ZipFile, asset_dir: str | Path | None) -> None:
    """Load costume surfaces for all targets."""
    for target in runtime.targets:
        for costume in target.costumes:
            _load_costume_image(costume, zf, asset_dir)


def _load_costume_image(
    costume: Costume, zf: zipfile.ZipFile, asset_dir: str | Path | None
) -> None:
    if costume.surface is not None:
        return
    if not costume.md5ext:
        _make_placeholder(costume)
        return
    image_data = _read_asset_data(costume.md5ext, zf, asset_dir)
    if image_data is None:
        _make_placeholder(costume)
        return
    if costume.data_format == 'svg':
        _rasterise_svg(costume, image_data)
    else:
        _load_bitmap(costume, image_data)


def _read_asset_data(
    filename: str, zf: zipfile.ZipFile, asset_dir: str | Path | None
) -> bytes | None:
    """Read asset bytes from the zip, or from a pre-extracted directory."""
    # Try pre-extracted directory first
    if asset_dir is not None:
        asset_path = Path(asset_dir) / filename
        if asset_path.is_file():
            return asset_path.read_bytes()

    # Fall back to zip contents
    try:
        return zf.read(filename)
    except KeyError:
        return None


def _load_bitmap(costume: Costume, data: bytes) -> None:
    costume.data = data
    try:
        buf = io.BytesIO(data)
        surf = pygame.image.load(buf)
        costume.surface = surf
    except (pygame.error, Exception) as exc:
        logger.warning('Failed to load image for %s: %s', costume.name, exc)
        _make_placeholder(costume)


def _rasterise_svg(costume: Costume, data: bytes) -> None:
    costume.data = data
    try:
        import cairosvg  # type: ignore[import-untyped]

        png_data = cairosvg.svg2png(bytestring=data, scale=1)
        buf = io.BytesIO(png_data)
        surf = pygame.image.load(buf)
        costume.surface = surf
    except Exception as exc:
        logger.warning('Failed to rasterise SVG %s: %s', costume.name, exc)
        _make_placeholder(costume)


def _make_placeholder(costume: Costume) -> None:
    """Assign a visible placeholder surface so the costume shows up
    in the renderer even without image data."""
    surf = pygame.Surface((50, 50), pygame.SRCALPHA)
    surf.fill((180, 180, 200, 200))
    pygame.draw.rect(surf, (100, 100, 120), surf.get_rect(), 2)
    costume.surface = surf


def _load_sounds(runtime: Runtime, zf: zipfile.ZipFile, asset_dir: str | Path | None) -> None:
    """Load sound data for all targets."""
    if not pygame.mixer.get_init():
        return  # mixer not available
    for target in runtime.targets:
        for sound in target.sounds:
            _load_sound_data(sound, zf, asset_dir)


def _load_sound_data(sound: Sound, zf: zipfile.ZipFile, asset_dir: str | Path | None) -> None:
    if not sound.md5ext:
        return
    data = _read_asset_data(sound.md5ext, zf, asset_dir)
    if data is None:
        return
    sound.data = data
    if not pygame.mixer.get_init():
        return


# ═══════════════════════════════════════════════════════════════════════
#  Serializer — data model → Scratch JSON
# ═══════════════════════════════════════════════════════════════════════


def _serialize_block(block: Block) -> dict[str, Any]:
    """Convert a Block to Scratch JSON format."""
    obj: dict[str, Any] = {
        'opcode': block.opcode,
        'next': block.next,
        'parent': block.parent,
        'shadow': block.shadow,
        'topLevel': block.top_level,
    }
    if block.x is not None:
        obj['x'] = block.x
    if block.y is not None:
        obj['y'] = block.y

    inputs: dict[str, list[Any]] = {}
    for name, inp in block.inputs.items():
        inputs[name] = _serialize_input(inp)
    if inputs:
        obj['inputs'] = inputs
    else:
        obj['inputs'] = {}

    fields: dict[str, list[Any]] = {}
    for name, fld in block.fields.items():
        fields[name] = _serialize_field(fld)
    if fields:
        obj['fields'] = fields
    else:
        obj['fields'] = {}

    return obj


def _serialize_input(inp: Input) -> list[Any]:
    """Serialize an Input to Scratch ``[shadow_flag, value]`` format."""
    shadow_flag = 1 if inp.shadow else 2
    return [shadow_flag, inp.value]


def _serialize_field(fld: Field) -> list[Any]:
    """Serialize a Field to Scratch ``[value, id]`` format."""
    return [fld.value, fld.id]


def _serialize_target(target: Target) -> dict[str, Any]:
    """Serialize a Target to Scratch JSON format."""
    variables: dict[str, list[Any]] = {}
    for vid, var in target.variables.items():
        variables[vid] = [var.name, var.value]

    lists: dict[str, list[Any]] = {}
    for lid, lst in target.lists.items():
        lists[lid] = [lst.name, list(lst.contents)]

    blocks: dict[str, dict[str, Any]] = {}
    for bid, block in target.blocks.items():
        blocks[bid] = _serialize_block(block)

    data: dict[str, Any] = {
        'isStage': target.is_stage,
        'name': target.name,
        'variables': variables,
        'lists': lists,
        'broadcasts': {},
        'blocks': blocks,
        'comments': {},
        'currentCostume': target.current_costume,
        'costumes': [_serialize_costume(c) for c in target.costumes],
        'sounds': [_serialize_sound(s) for s in target.sounds],
        'volume': target.volume,
        'layerOrder': target.layer_order,
        'tempo': 60,
        'videoTransparency': 50,
        'videoState': 'on',
        'textToSpeechLanguage': None,
    }

    if not target.is_stage:
        data.update(
            {
                'x': target.x,
                'y': target.y,
                'direction': target.direction,
                'size': target.size,
                'visible': target.visible,
                'rotationStyle': target.rotation_style,
                'draggable': target.draggable,
            }
        )

    return data


def _serialize_costume(costume: Costume) -> dict[str, Any]:
    """Serialize a Costume to Scratch JSON format."""
    return {
        'name': costume.name,
        'dataFormat': costume.data_format,
        'bitmapResolution': costume.bitmap_resolution,
        'rotationCenterX': costume.rotation_center_x,
        'rotationCenterY': costume.rotation_center_y,
        'assetId': costume.asset_id,
        'md5ext': costume.md5ext,
    }


def _serialize_sound(sound: Sound) -> dict[str, Any]:
    """Serialize a Sound to Scratch JSON format."""
    return {
        'name': sound.name,
        'dataFormat': sound.data_format,
        'rate': sound.rate,
        'sampleCount': sound.sample_count,
        'assetId': sound.asset_id,
        'md5ext': sound.md5ext,
    }


def _build_project_json(runtime: Runtime) -> dict[str, Any]:
    """Build the full project.json dict from a Runtime."""
    return {
        'targets': [_serialize_target(t) for t in runtime.targets],
        'monitors': [],
        'extensions': [],
        'meta': {
            'semver': '3.0.0',
            'vm': '0.2.0',
            'agent': 'py-scratch',
        },
    }


# ═══════════════════════════════════════════════════════════════════════
#  Save — Runtime → .sb3 file
# ═══════════════════════════════════════════════════════════════════════


def save_project(runtime: Runtime, path: str | Path | io.IOBase) -> None:
    """Serialize a Runtime into an .sb3 file at ``path``.
    ``path`` can be a file path or a file-like object (e.g. ``io.BytesIO``).
    """
    if isinstance(path, (str, Path)):
        path = Path(path)
    project_json = _build_project_json(runtime)

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Write project.json
        zf.writestr('project.json', json.dumps(project_json, separators=(',', ':')))

        # Write costume assets
        for target in runtime.targets:
            for costume in target.costumes:
                _write_asset(zf, costume.md5ext, costume.data)

        # Write sound assets
        for target in runtime.targets:
            for sound in target.sounds:
                _write_asset(zf, sound.md5ext, sound.data)


def _write_asset(zf: zipfile.ZipFile, md5ext: str, data: bytes) -> None:
    """Write a single asset into the zip if it has data."""
    if md5ext and data:
        zf.writestr(md5ext, data)
