"""
sb3 — load and unpack Scratch 3.0 project files (.sb3).

An .sb3 file is a ZIP archive containing ``project.json`` and asset
files (costume images, sounds).  This module loads/saves projects
and manages asset loading.

Parsing (JSON → data model) is in ``parse.py``.
Serialization (data model → JSON) is in ``serialize.py``.
See ``docs/sb3-serialization.md`` for the full format spec.
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
from ..vm.types import Costume, Sound
from .parse import parse_target
from .serialize import build_project_json

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  Top-level loader
# ═══════════════════════════════════════════════════════════════════════


def load_project(path: str | Path | io.IOBase) -> Runtime:
    """Load an .sb3 file and return a configured Runtime."""
    if isinstance(path, (str, Path)):
        path = Path(path)
        if not path.suffix == ".sb3":
            msg = f"Expected .sb3 file, got {path.suffix}"
            raise ValueError(msg)
        with zipfile.ZipFile(path) as zf:
            data = json.loads(zf.read("project.json"))
    else:
        data = _read_json_from_stream(path)
    return _from_json(data, path if isinstance(path, Path) else Path())


def _read_json_from_stream(stream: io.IOBase) -> dict[str, Any]:
    buf = io.BytesIO(stream.read())
    with zipfile.ZipFile(buf) as zf:
        return json.loads(zf.read("project.json"))  # type: ignore[no-any-return]


def _from_json(data: dict[str, Any], source_path: Path) -> Runtime:  # noqa: ARG001
    """Convert parsed project.json into a populated Runtime."""
    rt = Runtime()
    for target_data in data.get("targets", []):
        target = parse_target(target_data)
        rt.add_target(target)
    return rt


# ═══════════════════════════════════════════════════════════════════════
#  Asset loading
# ═══════════════════════════════════════════════════════════════════════


def load_assets(
    runtime: Runtime,
    source_path: str | Path | io.IOBase,
    asset_dir: str | Path | None = None,
) -> None:
    """Load costume images and sounds from the sb3 archive."""
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
    costume.data = image_data


def _read_asset_data(
    filename: str, zf: zipfile.ZipFile, asset_dir: str | Path | None
) -> bytes | None:
    """Read asset bytes from the zip, or from a pre-extracted directory."""
    if asset_dir is not None:
        asset_path = Path(asset_dir) / filename
        if asset_path.is_file():
            return asset_path.read_bytes()
    try:
        return zf.read(filename)
    except KeyError:
        return None


def _make_placeholder(costume: Costume) -> None:
    """Mark the costume as having no usable data."""
    costume.surface = None


def _load_sounds(runtime: Runtime, zf: zipfile.ZipFile, asset_dir: str | Path | None) -> None:
    """Load sound data for all targets."""
    if not pygame.mixer.get_init():
        return
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
    try:
        sound.sound = pygame.mixer.Sound(buffer=data)
    except pygame.error:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Save — Runtime → .sb3 file
# ═══════════════════════════════════════════════════════════════════════


def save_project(runtime: Runtime, path: str | Path | io.IOBase) -> None:
    """Serialize a Runtime into an .sb3 file at ``path``."""
    path_obj: str | Path | io.IOBase = Path(path) if isinstance(path, (str, Path)) else path
    project_json = build_project_json(runtime)

    with zipfile.ZipFile(path_obj, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(project_json, separators=(",", ":")))

        written: set[str] = set()
        for target in runtime.targets:
            for costume in target.costumes:
                _write_asset(zf, costume.md5ext, costume.data, written)
        for target in runtime.targets:
            for sound in target.sounds:
                _write_asset(zf, sound.md5ext, sound.data, written)


def _write_asset(
    zf: zipfile.ZipFile,
    md5ext: str,
    data: bytes,
    written: set[str] | None = None,
) -> None:
    """Write a single asset into the zip if it has data."""
    if md5ext and data and (written is None or md5ext not in written):
        zf.writestr(md5ext, data)
        if written is not None:
            written.add(md5ext)
