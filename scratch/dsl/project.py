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
import io as _io_module
import pygame
import uuid
from pathlib import Path
from typing import Any, Callable

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
        data_format: str = 'png',
        asset_id: str = '',
        md5ext: str = '',
    ) -> None:
        """Add a costume to this target."""
        self._costumes.append(
            Costume(
                name=name,
                data_format=data_format,
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
        """Ensure all costumes have valid image data for .sb3 export.

        Costumes with empty ``md5ext`` get a minimal placeholder PNG
        generated via pygame so the .sb3 file is valid for the Scratch editor.
        """
        for costume in pt._costumes:
            if costume.md5ext:
                continue  # already has asset data

            # Derive color from costume name
            name_hash = hashlib.md5(costume.name.encode()).hexdigest()
            r = (int(name_hash[0:2], 16) % 156) + 100
            g = (int(name_hash[2:4], 16) % 156) + 100
            b = (int(name_hash[4:6], 16) % 156) + 100

            surf = pygame.Surface((50, 50), pygame.SRCALPHA)
            surf.fill((r, g, b, 255))
            pygame.draw.circle(surf, (r - 20, g - 20, b - 20), (25, 25), 22)
            pygame.draw.circle(surf, (r - 80, g - 80, b - 80), (25, 25), 22, 2)

            buf = _io_module.BytesIO()
            pygame.image.save(surf, buf, 'PNG')
            png_bytes = buf.getvalue()

            md5 = hashlib.md5(png_bytes).hexdigest()
            costume.data_format = 'png'
            costume.asset_id = md5
            costume.md5ext = f'{md5}.png'
            costume.data = png_bytes
            costume.surface = surf

    def build_runtime(self) -> Runtime:
        """Construct a Runtime from all ProjectTargets and build scripts."""
        rt = Runtime()

        for pt in [self._stage, *self._sprites]:
            self._ensure_costume_data(pt)

            target = Target(name=pt.name, is_stage=pt.is_stage)
            target.x = pt.x
            target.y = pt.y
            target.direction = pt.direction
            target.size = pt.size
            target.visible = pt.visible
            target.layer_order = pt.layer_order
            target.costumes = list(pt._costumes)
            # If no costumes, add a minimal placeholder
            if not target.costumes:
                placeholder = _make_placeholder_costume(pt.name)
                target.costumes = [placeholder]

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

    def save(self, path: str | Path | _io_module.IOBase) -> None:
        """Construct the Runtime and save as .sb3."""
        rt = self.build_runtime()
        save_project(rt, path)


def _make_placeholder_costume(name: str) -> Costume:
    """Generate a minimal placeholder costume with a colored circle.

    Used when a target has no costumes at all, ensuring the .sb3 is
    valid for the Scratch editor.  The color varies by target name
    so different targets produce distinct image assets.
    """
    # Derive color from target name to avoid identical placeholders
    name_hash = hashlib.md5(name.encode()).hexdigest()
    r = (int(name_hash[0:2], 16) % 156) + 100
    g = (int(name_hash[2:4], 16) % 156) + 100
    b = (int(name_hash[4:6], 16) % 156) + 100

    surf = pygame.Surface((50, 50), pygame.SRCALPHA)
    surf.fill((r, g, b, 255))
    pygame.draw.circle(surf, (r - 20, g - 20, b - 20), (25, 25), 22)
    pygame.draw.circle(surf, (r - 80, g - 80, b - 80), (25, 25), 22, 2)

    buf = _io_module.BytesIO()
    pygame.image.save(surf, buf, 'PNG')
    png_bytes = buf.getvalue()

    md5 = hashlib.md5(png_bytes).hexdigest()
    return Costume(
        name=name or 'costume1',
        data_format='png',
        bitmap_resolution=1,
        rotation_center_x=25,
        rotation_center_y=25,
        asset_id=md5,
        md5ext=f'{md5}.png',
        data=png_bytes,
        surface=surf,
    )
