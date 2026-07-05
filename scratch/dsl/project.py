"""
Project — high-level entry point for the Scratch DSL.

Usage::

    from pathlib import Path

    project = Project("My Game", assets_dir=Path(__file__).parent / "assets")
    sprite = project.sprite("Cat")
    sprite.var("score", 0)

    # Costume filename resolved against ``assets_dir``
    sprite.costume("Cat", "cat.svg")

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
from scratch.vm.target import ListVar, Target, Variable
from scratch.vm.types import Costume, Sound

from .builder import Script
from .expr import Reporter, StackExpr
from . import events as _events
from . import procedures as _procedures


class ProjectTarget:
    """A sprite or stage under construction in a Project.

    Manages scripts, variables, and basic properties.  Converted to a
    ``scratch.vm.target.Target`` during ``Project.build_runtime()``.
    """

    def __init__(
        self,
        name: str = 'Sprite',
        is_stage: bool = False,
        assets_dir: str | Path | None = None,
    ) -> None:
        self.name = name
        self.is_stage = is_stage
        self.assets_dir = Path(assets_dir) if assets_dir else None
        self._scripts: list[Script] = []
        self._variables: dict[str, Any] = {}  # name → default value
        self._lists: dict[str, ListVar] = {}
        self._costumes: list[Costume] = []
        self._sounds: list[Sound] = []
        self.x: float = 0.0
        self.y: float = 0.0
        self.direction: float = 90.0
        self.size: float = 100.0
        self.rotation_style: str = 'all around'
        self.visible: bool = True
        self.layer_order: int = 1 if not is_stage else 0

    def var(self, name: str, default: Any = 0) -> None:
        """Declare a variable.  Raises ``ValueError`` on duplicate name."""
        if name in self._variables:
            raise ValueError(f"Variable '{name}' already exists")
        self._variables[name] = default

    def list_(self, name: str, items: list[Any] | None = None) -> None:
        """Declare a list with optional initial items.

        Usage::

            sprite.list_("scores", [10, 20, 30])
        """
        lid = uuid.uuid4().hex[:8]
        self._lists[lid] = ListVar(name=name, contents=list(items or []))

    def _resolve_asset(self, filename: str | Path) -> Path:
        """Resolve *filename* to an absolute path using the target's assets_dir."""
        p = Path(filename)
        if p.is_absolute():
            return p
        if self.assets_dir is not None:
            return self.assets_dir / p
        return p

    def costume(
        self,
        name: str,
        filename: str | Path | None = None,
        *,
        path: str | Path | None = None,
        data_format: str = 'png',
        asset_id: str = '',
        md5ext: str = '',
        rotation_center_x: float | None = None,
        rotation_center_y: float | None = None,
    ) -> None:
        """Add a costume to this target.

        Usage::

            # Simple: filename resolved against ``assets_dir`` (set on Project)
            sprite.costume("Cat", "cat.svg")

            # Explicit path (no assets_dir needed)
            sprite.costume("Cat", path="/path/to/cat.png")

        If *filename* is given (positional), it is resolved against the
        project's ``assets_dir`` when set.  If *path* is given (keyword),
        it is used as-is.

        For SVG files the rotation centre defaults to the viewBox centre;
        pass ``rotation_center_x`` / ``rotation_center_y`` to override.
        """
        src = path or filename
        if src is None:
            self._costumes.append(
                Costume(
                    name=name,
                    data_format=data_format,
                    rotation_center_x=rotation_center_x or 0,
                    rotation_center_y=rotation_center_y or 0,
                    asset_id=asset_id,
                    md5ext=md5ext,
                )
            )
            return

        src_path = self._resolve_asset(src)
        data = src_path.read_bytes()
        fmt = src_path.suffix.lstrip('.')
        md5 = hashlib.md5(data).hexdigest()

        rc_x: float = rotation_center_x or 0
        rc_y: float = rotation_center_y or 0

        # For SVG, default rotation centre = centre of viewBox
        if fmt == 'svg' and rotation_center_x is None:
            # find rotation center in viewBox attribute, e.g. viewBox="0 0 480 360"
            m = re.search(
                r'viewBox="-?[\d.]+\s+-?[\d.]+\s+([\d.]+)\s+([\d.]+)"', data.decode('utf-8')
            )
            if m:
                vb_w = float(m.group(1))
                vb_h = float(m.group(2))
                rc_x = rc_x or (vb_w / 2)
                rc_y = rc_y or (vb_h / 2)

        self._costumes.append(
            Costume(
                name=name,
                data_format=fmt,
                data=data,
                rotation_center_x=rc_x,
                rotation_center_y=rc_y,
                asset_id=md5,
                md5ext=f'{md5}.{fmt}',
            )
        )

    def sound(
        self,
        name: str,
        filename: str | Path | None = None,
        *,
        path: str | Path | None = None,
    ) -> None:
        """Add a sound to this target from a file.

        Usage::

            sprite.sound("pop", "pop.wav")
            sprite.sound("pop", path="/path/to/pop.wav")

        If *filename* is given (positional), it is resolved against the
        project's ``assets_dir`` when set.
        """
        src = path or filename
        if src is None:
            return
        src_path = self._resolve_asset(src)
        data = src_path.read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        self._sounds.append(
            Sound(
                name=name,
                data_format=src_path.suffix.lstrip('.'),
                data=data,
                asset_id=md5,
                md5ext=f'{md5}.{src_path.suffix.lstrip(".")}',
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

    def when_this_sprite_clicked(self, *body: StackExpr) -> None:
        """Register a when-this-sprite-clicked script."""
        self._scripts.append(Script(hat=_events.when_this_sprite_clicked(), body=list(body)))

    def when_backdrop_switches_to(self, backdrop: str = 'next backdrop') -> Callable[..., None]:
        """Return a callable for when-backdrop-switches-to scripts.

        Usage::

            stage.when_backdrop_switches_to("dark")(...)
        """
        hat = _events.when_backdrop_switches_to(backdrop=backdrop)

        def _reg(*body: StackExpr) -> None:
            self._scripts.append(Script(hat=hat, body=list(body)))

        return _reg

    def when_greater_than(
        self, metric: str = 'loudness', value: int | float | Reporter = 10
    ) -> Callable[..., None]:
        """Return a callable for when-greater-than scripts."""
        hat = _events.when_greater_than(metric=metric, value=value)

        def _reg(*body: StackExpr) -> None:
            self._scripts.append(Script(hat=hat, body=list(body)))

        return _reg

    def when_start_as_clone(self, *body: StackExpr) -> None:
        """Register a when-start-as-clone script."""
        self._scripts.append(
            Script(hat=StackExpr(opcode='control_start_as_clone'), body=list(body))
        )

    def define(self, proc_name: str, *param_names: str) -> Callable[..., None]:
        """Define a custom block (My Block) procedure on this sprite.

        Usage::

            sprite.define('step %s %n', 'dir', 'px')(
                motion.change_x(procedures.arg('px')),
            )

        Args:
            proc_name: The proccode (e.g. ``"step %s %n"``).
            *param_names: Parameter names, one per ``%`` placeholder.

        Returns:
            A callable that accepts the procedure body blocks.
        """
        hat = _procedures.define(proc_name, *param_names)

        def _reg(*body: StackExpr) -> None:
            self._scripts.append(Script(hat=hat, body=list(body)))

        return _reg


class Project:
    """High-level project entry point.

    Manages the stage, sprites, and produces an .sb3 file.
    """

    def __init__(self, name: str = 'Project', assets_dir: str | Path | None = None) -> None:
        self.name = name
        self.assets_dir = Path(assets_dir) if assets_dir else None
        self._stage = ProjectTarget(name='Stage', is_stage=True, assets_dir=self.assets_dir)
        self._sprites: list[ProjectTarget] = []

    def sprite(self, name: str) -> ProjectTarget:
        """Add and return a new sprite target."""
        t = ProjectTarget(name=name, is_stage=False, assets_dir=self.assets_dir)
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
            target.rotation_style = pt.rotation_style
            target.visible = pt.visible
            target.layer_order = pt.layer_order
            target.costumes = list(pt._costumes)
            target.sounds = list(pt._sounds)

            # Stage must have at least one backdrop (Scratch 3 schema requirement).
            if target.is_stage and not target.costumes:
                _add_white_backdrop(target)

            # Generate variable UUIDs and register on target
            var_map = pt._make_var_map()
            var_map_rev: dict[str, str] = {}
            for name, vid in var_map.items():
                var_map_rev[vid] = name
                target.variables[vid] = Variable(name=name, value=pt._variables[name])

            # Transfer lists
            for lid, lst in pt._lists.items():
                target.lists[lid] = lst

            # Include stage variables in var_map so scripts on sprites can
            # reference stage variables by name (e.g. ``data.variable('beat')``).
            if not target.is_stage and self._stage is not None:
                stage_var_map = self._stage._make_var_map()
                var_map = {**var_map, **stage_var_map}

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
