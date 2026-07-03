"""
Project — high-level entry point for the Scratch DSL.

Usage::

    project = Project("My Game")
    sprite = project.sprite("Cat")
    sprite.var("score", 0)

    sprite.when_flag_clicked(
        motion.move(10),
        motion.turn_right(15),
    )

    project.save("game.sb3")
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
from pathlib import Path
from typing import Any, Callable

import pygame

from scratch.sb3.io import save_project
from scratch.vm.opcodes import OPCODE_MAP
from scratch.vm.runtime import Runtime
from scratch.vm.target import Target, Variable
from scratch.vm.types import Costume

from .builder import Script
from .expr import StackExpr
from . import events as _events


class ProjectTarget:
    """A sprite or stage under construction in a Project.

    Manages scripts, variables, and basic properties.  Converted to a
    ``scratch.vm.target.Target`` during ``Project.build_runtime()``.
    """

    def __init__(self, name: str = 'Sprite', is_stage: bool = False) -> None:
        self.name = name
        self.is_stage = is_stage
        self._scripts: list[Script] = []
        self._variables: dict[str, Any] = {}  # name → default value
        self._costumes: list[Costume] = []
        self.x: float = 0.0
        self.y: float = 0.0
        self.direction: float = 90.0
        self.size: float = 100.0
        self.visible: bool = True
        self.layer_order: int = 1 if not is_stage else 0

    def var(self, name: str, default: Any = 0) -> None:
        """Declare a variable.  Raises ``ValueError`` on duplicate name."""
        if name in self._variables:
            raise ValueError(f"Variable '{name}' already exists")
        self._variables[name] = default

    def costume(
        self,
        name: str,
        *,
        path: str | None = None,
        data_format: str = 'png',
        asset_id: str = '',
        md5ext: str = '',
        rotation_center_x: float | None = None,
        rotation_center_y: float | None = None,
    ) -> None:
        """Add a costume to this target.

        If *path* is given, the costume data is loaded from that file and
        the format is inferred from the extension (``.svg``, ``.png``, etc.).
        For SVG files the rotation centre defaults to the viewBox centre;
        pass ``rotation_center_x`` / ``rotation_center_y`` to override.
        """
        rc_x: float = rotation_center_x or 0
        rc_y: float = rotation_center_y or 0

        if path is not None:
            data = Path(path).read_bytes()
            fmt = Path(path).suffix.lstrip('.')
            md5 = hashlib.md5(data).hexdigest()

            # For SVG, default rotation centre = centre of viewBox
            if fmt == 'svg' and rotation_center_x is None:
                m = re.search(
                    r'viewBox="-?[\d.]+\s+-?[\d.]+\s+([\d.]+)\s+([\d.]+)"', data.decode('utf-8')
                )
                if m:
                    vb_w = float(m.group(1))
                    vb_h = float(m.group(2))
                    rc_x = rc_x or (vb_w / 2)
                    rc_y = rc_y or (vb_h / 2)

            # Load surface immediately so scratch_bounds work for bounce etc.
            surface = None
            if fmt == 'svg':
                try:
                    surface = pygame.image.load(io.BytesIO(data), 'svg')
                except Exception:  # noqa: BLE001
                    pass

            self._costumes.append(
                Costume(
                    name=name,
                    data_format=fmt,
                    data=data,
                    surface=surface,
                    rotation_center_x=rc_x,
                    rotation_center_y=rc_y,
                    asset_id=md5,
                    md5ext=f'{md5}.{fmt}',
                )
            )
            return

        rc_x = rotation_center_x or 0
        rc_y = rotation_center_y or 0
        self._costumes.append(
            Costume(
                name=name,
                data_format=data_format,
                rotation_center_x=rc_x,
                rotation_center_y=rc_y,
                asset_id=asset_id,
                md5ext=md5ext,
            )
        )

    def _make_var_map(self) -> dict[str, str]:
        """Generate UUIDs for all declared variables."""
        return {name: uuid.uuid4().hex[:8] for name in self._variables}

    def when_flag_clicked(self, *body: StackExpr) -> None:
        """Register a when-flag-clicked script."""
        self._scripts.append(Script(hat=_events.when_flag_clicked(), body=list(body)))

    def when_key_pressed(self, key: str) -> Callable[..., None]:
        """Return a callable for when-key-pressed scripts.

        Usage::

            sprite.when_key_pressed("space")(motion.move(10))
        """
        hat = _events.when_key_pressed(key=key)

        def _reg(*body: StackExpr) -> None:
            self._scripts.append(Script(hat=hat, body=list(body)))

        return _reg

    def when_broadcast_received(self, message: str = '') -> Callable[..., None]:
        """Return a callable for when-broadcast-received scripts.

        Usage::

            sprite.when_broadcast_received("message")(motion.move(10))
        """
        hat = _events.when_broadcast_received(message=message)

        def _reg(*body: StackExpr) -> None:
            self._scripts.append(Script(hat=hat, body=list(body)))

        return _reg


class Project:
    """High-level project entry point.

    Manages the stage, sprites, and produces an .sb3 file.
    """

    def __init__(self, name: str = 'Project') -> None:
        self.name = name
        self._stage = ProjectTarget(name='Stage', is_stage=True)
        self._sprites: list[ProjectTarget] = []

    def sprite(self, name: str) -> ProjectTarget:
        """Add and return a new sprite target."""
        t = ProjectTarget(name=name, is_stage=False)
        self._sprites.append(t)
        return t

    @property
    def stage(self) -> ProjectTarget:
        return self._stage

    def _ensure_costume_data(self, pt: ProjectTarget) -> None:
        """No-op — placeholder costumes are no longer generated."""

    def build_runtime(self) -> Runtime:
        """Construct a Runtime from all ProjectTargets and build scripts."""
        rt = Runtime()

        for pt in [self._stage, *self._sprites]:
            target = Target(name=pt.name, is_stage=pt.is_stage)
            target.x = pt.x
            target.y = pt.y
            target.direction = pt.direction
            target.size = pt.size
            target.visible = pt.visible
            target.layer_order = pt.layer_order
            target.costumes = list(pt._costumes)

            # Stage must have at least one backdrop (Scratch 3 schema requirement).
            if target.is_stage and not target.costumes:
                _add_white_backdrop(target)

            # Generate variable UUIDs and register on target
            var_map = pt._make_var_map()
            var_map_rev: dict[str, str] = {}
            for name, vid in var_map.items():
                var_map_rev[vid] = name
                target.variables[vid] = Variable(name=name, value=pt._variables[name])

            # Build all scripts with var_map
            for script in pt._scripts:
                script.var_map = var_map
                script.build(target)

            rt.add_target(target)

        rt.register_all(OPCODE_MAP)

        return rt

    def save(self, path: str | Path | io.IOBase) -> None:
        """Construct the Runtime and save as .sb3."""
        rt = self.build_runtime()
        save_project(rt, path)


def _add_white_backdrop(target: Target) -> None:
    """Add a minimal white 480x360 SVG backdrop to *target*."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg"'
        ' viewBox="0 0 480 360" width="480" height="360">'
        '<rect width="480" height="360" fill="white"/></svg>'
    ).encode('utf-8')
    md5 = hashlib.md5(svg).hexdigest()
    target.costumes.append(
        Costume(
            name='Stage',
            data_format='svg',
            data=svg,
            surface=pygame.image.load(io.BytesIO(svg), 'svg'),
            rotation_center_x=240,
            rotation_center_y=180,
            asset_id=md5,
            md5ext=f'{md5}.svg',
        )
    )
