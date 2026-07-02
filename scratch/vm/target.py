"""
Target — a sprite or the stage in a Scratch project.

Each target holds its own block tree, variables, lists, costumes, and
rendering state (position, direction, size, visibility).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .constants import (
    DEFAULT_DIRECTION,
    DEFAULT_LAYER_ORDER,
    DEFAULT_PEN_BRIGHTNESS,
    DEFAULT_PEN_COLOR,
    DEFAULT_PEN_SIZE,
    DEFAULT_PEN_SATURATION,
    DEFAULT_SIZE_PCT,
    DEFAULT_TEMPO_BPM,
    DEFAULT_VOLUME_PCT,
    GRAPHIC_EFFECTS,
    ROTATION_ALL_AROUND,
    SOUND_EFFECT_PAN,
    SOUND_EFFECT_PITCH,
)

from .types import Block, Costume, Sound

# ── Variable & List wrappers ─────────────────────────────────────────────


@dataclass
class Variable:
    """A Scratch variable (mutable)."""

    name: str
    value: Any = 0
    is_cloud: bool = False  # stored on server (unused here)

    def __repr__(self) -> str:
        return f'Var({self.name}={self.value!r})'


@dataclass
class ListVar:
    """A Scratch list (mutable)."""

    name: str
    contents: list[Any] = field(default_factory=list)
    is_cloud: bool = False

    def __repr__(self) -> str:
        return f'List({self.name}, len={len(self.contents)})'


# ── Broadcast message ────────────────────────────────────────────────────


@dataclass
class BroadcastMsg:
    """A named broadcast message."""

    name: str

    def __hash__(self) -> int:
        return hash(self.name)


# ── Target ───────────────────────────────────────────────────────────────


@dataclass
class Target:
    """A sprite or the stage.

    The stage (``is_stage=True``) has no position/motion attributes but can
    switch backdrops and has its own block tree for backdrop scripts.
    """

    name: str = 'Stage'
    is_stage: bool = False
    _is_clone: bool = False

    # ── Scripts ───────────────────────────────────────────────────────
    blocks: dict[str, Block] = field(default_factory=dict)

    # ── Data ──────────────────────────────────────────────────────────
    variables: dict[str, Variable] = field(default_factory=dict)
    # Maps variable ID (or name) → Variable — in Scratch JSON the key is
    # the variable ID; for runtime we also accept name-based lookups.
    lists: dict[str, ListVar] = field(default_factory=dict)
    broadcasts: dict[str, BroadcastMsg] = field(default_factory=dict)

    # ── Costumes & sounds ─────────────────────────────────────────────
    costumes: list[Costume] = field(default_factory=list)
    costume_index: int = 0  # 0-based
    sounds: list[Sound] = field(default_factory=list)

    # ── Motion (sprites only) ─────────────────────────────────────────
    _x: float = 0.0
    _y: float = 0.0
    _direction: float = DEFAULT_DIRECTION
    size: float = DEFAULT_SIZE_PCT
    rotation_style: str = ROTATION_ALL_AROUND

    @property
    def x(self) -> float:
        return self._x

    @x.setter
    def x(self, val: float) -> None:
        self._x = round(val)

    @property
    def y(self) -> float:
        return self._y

    @y.setter
    def y(self, val: float) -> None:
        self._y = round(val)

    def set_xy(self, x: float, y: float) -> None:
        self.x = x
        self.y = y

    @property
    def direction(self) -> float:
        return self._direction

    @direction.setter
    def direction(self, val: float) -> None:
        norm = val % 360
        self._direction = norm if norm <= 180 else norm - 360

    # ── Looks ─────────────────────────────────────────────────────────
    visible: bool = True
    volume: float = DEFAULT_VOLUME_PCT
    layer_order: int = DEFAULT_LAYER_ORDER
    say_text: str | None = None
    say_until: float | None = None

    sound_effects: dict[str, float] = field(
        default_factory=lambda: {SOUND_EFFECT_PITCH: 0.0, SOUND_EFFECT_PAN: 0.0}
    )

    # ── Tempo (Music extension, stored on stage) ──────────────────────
    tempo: float = DEFAULT_TEMPO_BPM

    # ── Effects ───────────────────────────────────────────────────────
    effects: dict[str, float] = field(default_factory=lambda: {name: 0 for name in GRAPHIC_EFFECTS})
    # ── Draggable ─────────────────────────────────────────────────────
    draggable: bool = False

    # ── Pen ───────────────────────────────────────────────────────────
    pen_down: bool = False
    pen_color: tuple[int, int, int] = DEFAULT_PEN_COLOR
    pen_size: float = DEFAULT_PEN_SIZE
    pen_saturation: float = DEFAULT_PEN_SATURATION
    pen_brightness: float = DEFAULT_PEN_BRIGHTNESS
    # Renderer-internal (set by pen opcodes)
    _pen_clear_requested: bool = False
    _stamp_queue: list[Any] = field(default_factory=list)

    # ── Scratch JSON properties (carried for completeness) ────────────
    comments: dict[str, Any] = field(default_factory=dict)

    # Pre-computed: all blocks that are top-level hat blocks, keyed by opcode
    _hat_cache: dict[str, list[str]] | None = None

    # ── Property helpers ──────────────────────────────────────────────

    @property
    def costume(self) -> Costume | None:
        if 0 <= self.costume_index < len(self.costumes):
            return self.costumes[self.costume_index]
        return None

    @property
    def current_costume_name(self) -> str:
        c = self.costume
        return c.name if c else ''

    # ── Variable & list access ────────────────────────────────────────

    def lookup_variable(self, name_or_id: str) -> Variable | None:
        """Find a variable by name or ID."""
        for v in self.variables.values():
            if v.name == name_or_id:
                return v
        return self.variables.get(name_or_id)

    def lookup_list(self, name_or_id: str) -> ListVar | None:
        for lst in self.lists.values():
            if lst.name == name_or_id:
                return lst
        return self.lists.get(name_or_id)

    # ── Block utilities ───────────────────────────────────────────────

    def get_hat_blocks(self, opcode: str) -> Iterable[Block]:
        if self._hat_cache is None:
            self._rebuild_hat_cache()

        assert self._hat_cache is not None
        for bid in self._hat_cache.get(opcode, []):
            yield self.blocks[bid]

    def get_hat_next_blocks(self, opcode: str) -> Iterable[str]:
        """
        Return list of executable blocks that follows the hat block
        """
        for block in self.get_hat_blocks(opcode):
            if block.next is not None:
                yield block.next

    def _rebuild_hat_cache(self) -> None:
        cache: dict[str, list[str]] = {}
        for bid, block in self.blocks.items():
            if block.top_level and (
                block.opcode.startswith('event_') or block.opcode == 'control_start_as_clone'
            ):
                cache.setdefault(block.opcode, []).append(bid)
        self._hat_cache = cache

    def invalidate_hat_cache(self) -> None:
        self._hat_cache = None

    # ── Rendering helpers ──────────────────────────────────────────────

    def scratch_bounds(self) -> tuple[float, float, float, float]:
        """Return (left, top, right, bottom) of the current costume
        in Scratch coordinates, or (0,0,0,0) if no costume.

        Scratch stage is 480×360, origin at centre.
        """
        if not self.costume or self.costume.surface is None:
            return (0, 0, 0, 0)
        surf = self.costume.surface
        w, h = surf.get_width(), surf.get_height()
        cx = self.costume.rotation_center_x
        cy = self.costume.rotation_center_y
        return (-cx, -cy, w - cx, h - cy)

    # ── Sound helpers ───────────────────────────────────────────────

    def find_sound(self, name: str) -> Sound | None:
        """Find a sound by name on this target."""
        for s in self.sounds:
            if s.name == name:
                return s
        return None

    def clone(self) -> Target:
        """Return a shallow clone for sprite cloning."""
        t = Target(
            name=self.name,
            is_stage=self.is_stage,
            blocks=self.blocks,
            variables={k: Variable(v.name, v.value, v.is_cloud) for k, v in self.variables.items()},
            lists={k: ListVar(v.name, v.contents) for k, v in self.lists.items()},
            broadcasts=self.broadcasts,
            costumes=self.costumes,
            sounds=self.sounds,
            _x=self.x,
            _y=self.y,
            _direction=self.direction,
            size=self.size,
            rotation_style=self.rotation_style,
            visible=self.visible,
            volume=self.volume,
            layer_order=self.layer_order,
            sound_effects=dict(self.sound_effects),
            tempo=self.tempo,
            effects=dict(self.effects),
            say_text=self.say_text,
            say_until=self.say_until,
        )
        return t
