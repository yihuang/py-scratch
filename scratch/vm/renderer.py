"""
Renderer — pygame-based stage and sprite drawing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pygame

from .runtime import Runtime
from .target import Target
from .types import Costume

if TYPE_CHECKING:
    pass


# ── Constants ────────────────────────────────────────────────────────────

STAGE_W = 480
STAGE_H = 360
STAGE_SCALE = 2  # scale factor for the window

WINDOW_W = STAGE_W * STAGE_SCALE
WINDOW_H = STAGE_H * STAGE_SCALE

SCRATCH_TO_PYGAME = (STAGE_W // 2, STAGE_H // 2)

# Colours
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_GREY = (200, 200, 200)
COLOR_STAGE_BG = (220, 220, 220)

# Keyboard mapping — Scratch key names → pygame key codes
KEY_MAP: dict[str, int] = {
    'space': pygame.K_SPACE,
    'left arrow': pygame.K_LEFT,
    'right arrow': pygame.K_RIGHT,
    'up arrow': pygame.K_UP,
    'down arrow': pygame.K_DOWN,
    'enter': pygame.K_RETURN,
    'a': pygame.K_a,
    'b': pygame.K_b,
    'c': pygame.K_c,
    'd': pygame.K_d,
    'e': pygame.K_e,
    'f': pygame.K_f,
    'g': pygame.K_g,
    'h': pygame.K_h,
    'i': pygame.K_i,
    'j': pygame.K_j,
    'k': pygame.K_k,
    'l': pygame.K_l,
    'm': pygame.K_m,
    'n': pygame.K_n,
    'o': pygame.K_o,
    'p': pygame.K_p,
    'q': pygame.K_q,
    'r': pygame.K_r,
    's': pygame.K_s,
    't': pygame.K_t,
    'u': pygame.K_u,
    'v': pygame.K_v,
    'w': pygame.K_w,
    'x': pygame.K_x,
    'y': pygame.K_y,
    'z': pygame.K_z,
    '0': pygame.K_0,
    '1': pygame.K_1,
    '2': pygame.K_2,
    '3': pygame.K_3,
    '4': pygame.K_4,
    '5': pygame.K_5,
    '6': pygame.K_6,
    '7': pygame.K_7,
    '8': pygame.K_8,
    '9': pygame.K_9,
}

# Reverse: pygame key code → Scratch key name
KEY_CODE_TO_NAME: dict[int, str] = {code: name for name, code in KEY_MAP.items()}


def scratch_to_screen(x: float, y: float) -> tuple[float, float]:
    """Convert Scratch coordinates to screen coordinates.

    Scratch: origin at centre, +x right, +y up.
    Screen: origin at top-left, +x right, +y down.
    """
    sx = (x + STAGE_W / 2) * STAGE_SCALE
    sy = (STAGE_H / 2 - y) * STAGE_SCALE
    return sx, sy


# ── Costume loading ──────────────────────────────────────────────────────


def _load_costume_surface(costume: Costume) -> pygame.Surface | None:
    if costume.surface is not None:
        surf = costume.surface
        assert isinstance(surf, pygame.Surface)
        return surf
    surf = pygame.Surface((50, 50), pygame.SRCALPHA)
    surf.fill((0, 0, 255, 128))
    pygame.draw.rect(surf, (100, 100, 255), (5, 5, 40, 40), 2)
    costume.surface = surf
    return surf


# ── Pen layer cache ──────────────────────────────────────────────────────


class PenLayer:
    """Manages a persistent surface for pen strokes."""

    def __init__(self) -> None:
        self.surface = pygame.Surface(
            (STAGE_W * STAGE_SCALE, STAGE_H * STAGE_SCALE),
            pygame.SRCALPHA,
        )
        self.surface.fill((0, 0, 0, 0))

    def clear(self) -> None:
        self.surface.fill((0, 0, 0, 0))

    def draw_line(
        self, x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int], size: float
    ) -> None:
        sx1, sy1 = scratch_to_screen(x1, y1)
        sx2, sy2 = scratch_to_screen(x2, y2)
        pygame.draw.line(
            self.surface,
            color,
            (sx1, sy1),
            (sx2, sy2),
            max(1, int(size * STAGE_SCALE)),
        )

    def draw_dot(self, x: float, y: float, color: tuple[int, int, int], size: float) -> None:
        sx, sy = scratch_to_screen(x, y)
        r = max(1, int(size * STAGE_SCALE / 2))
        pygame.draw.circle(self.surface, color, (int(sx), int(sy)), r)

    def stamp(
        self, surface: pygame.Surface, x: float, y: float, size: float, direction: float
    ) -> None:
        """Stamp a surface onto the pen layer."""
        sx, sy = scratch_to_screen(x, y)
        angle = -direction  # pygame angle convention
        rotated = pygame.transform.rotate(surface, angle)
        sw = rotated.get_width() * (size / 100)
        sh = rotated.get_height() * (size / 100)
        scaled = pygame.transform.scale(rotated, (max(1, int(sw)), max(1, int(sh))))
        rect = scaled.get_rect(center=(int(sx), int(sy)))
        self.surface.blit(scaled, rect)


# ── Renderer ─────────────────────────────────────────────────────────────


class Renderer:
    """Pygame-based stage + sprite renderer.

    Owns the display window and game loop.
    """

    def __init__(self, runtime: Runtime, title: str = 'Scratch VM') -> None:
        self.runtime = runtime
        self.title = title

        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()

        self.pen_layer = PenLayer()
        self._fps = 60
        self._running = False
        self._keys_down: set[int] = set()
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0
        self._mouse_down: bool = False

    # ── Keyboard state bridge ─────────────────────────────────────────
    def _sync_keyboard(self) -> None:
        pressed: dict[str, bool] = {}
        for name, code in KEY_MAP.items():
            pressed[name] = code in self._keys_down
        self.runtime._keyboard = pressed

    # ── Mouse state bridge ────────────────────────────────────────────

    def _sync_mouse(self) -> None:
        self.runtime._mouse_x = self._mouse_x
        self.runtime._mouse_y = self._mouse_y
        self.runtime._mouse_down = self._mouse_down

    # ── Main loop ─────────────────────────────────────────────────────

    def run(self) -> None:
        self.runtime.green_flag()
        self._running = True
        while self._running:
            self._handle_events()
            self._sync_keyboard()
            self._sync_mouse()
            self._update()
            self._draw()
            self.clock.tick(self._fps)
        pygame.quit()

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            match event.type:
                case pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._running = False
                        break
                    self._keys_down.add(event.key)
                    name = KEY_CODE_TO_NAME.get(event.key)
                    if name is not None:
                        self.runtime.start_key_hat(name)
                case pygame.MOUSEMOTION:
                    px, py = event.pos
                    self._mouse_x = px / STAGE_SCALE - STAGE_W / 2
                    self._mouse_y = -(py / STAGE_SCALE) + STAGE_H / 2
                case pygame.MOUSEBUTTONDOWN:
                    px, py = event.pos
                    self._mouse_x = px / STAGE_SCALE - STAGE_W / 2
                    self._mouse_y = -(py / STAGE_SCALE) + STAGE_H / 2
                    self._mouse_down = True
                    self.runtime.start_click_hat(self._mouse_x, self._mouse_y)
                case pygame.MOUSEBUTTONUP:
                    self._mouse_down = False

    def _update(self) -> None:
        """Step the runtime and update pen state."""
        # Check for pen clear requests
        if self.runtime.stage and getattr(self.runtime.stage, '_pen_clear_requested', False):
            self.pen_layer.clear()
            self.runtime.stage._pen_clear_requested = False

        # Handle stamp requests
        stamps = []
        if self.runtime.stage and hasattr(self.runtime.stage, '_stamp_queue'):
            stamps = self.runtime.stage._stamp_queue
            self.runtime.stage._stamp_queue = []

        for sx, sy, sz, sd, ci in stamps:
            target = None
            for t in self.runtime.sprite_targets():
                if t.costume_index == ci:
                    target = t
                    break
            if target and target.costume and target.costume.surface:
                self.pen_layer.stamp(
                    target.costume.surface,
                    sx,
                    sy,
                    sz,
                    sd,
                )

        # Step all threads
        self.runtime.step()

    # ── Drawing ───────────────────────────────────────────────────────

    def _draw(self) -> None:
        self.screen.fill(COLOR_STAGE_BG)

        # Draw stage area
        stage_rect = pygame.Rect(0, 0, WINDOW_W, WINDOW_H)
        self.screen.fill(COLOR_WHITE, stage_rect)

        # Draw stage backdrop if any
        stage = self.runtime.stage
        if stage and stage.costume and stage.costume.surface:
            self._draw_costume(stage, is_stage=True)

        # Draw sprite layers (sorted by layer_order)
        sprites = sorted(self.runtime.sprite_targets(), key=lambda t: t.layer_order)
        for sprite in sprites:
            if not sprite.visible:
                continue
            self._draw_sprite(sprite)

        # Draw pen layer on top
        self.screen.blit(self.pen_layer.surface, (0, 0))

        # Draw overlay info
        self._draw_info()

        pygame.display.flip()

    def _draw_sprite(self, sprite: Target) -> None:
        """Draw a sprite at its position with rotation and size."""
        if not sprite.costume:
            # Draw placeholder
            sx, sy = scratch_to_screen(sprite.x, sprite.y)
            sz = max(4, int(sprite.size * STAGE_SCALE / 100 * 20))
            rect = pygame.Rect(int(sx - sz / 2), int(sy - sz / 2), sz, sz)
            pygame.draw.ellipse(self.screen, (255, 0, 0), rect)
            pygame.draw.ellipse(self.screen, COLOR_BLACK, rect, 2)
            return

        if sprite.costume.surface is None:
            _load_costume_surface(sprite.costume)

        base = sprite.costume.surface
        if base is None:
            return

        # Apply size
        scale = sprite.size / 100.0
        w = max(1, int(base.get_width() * scale))
        h = max(1, int(base.get_height() * scale))

        try:
            scaled = pygame.transform.smoothscale(base, (w, h))
        except ValueError:
            scaled = base

        # Apply rotation
        angle = -sprite.direction  # pygame: + is CW, Scratch: + is CCW
        if angle != 0:
            if sprite.rotation_style == 'left-right':
                # Flip horizontally if facing left
                if sprite.direction < 0 or sprite.direction > 180:
                    scaled = pygame.transform.flip(scaled, True, False)
            elif sprite.rotation_style == "don't rotate":
                pass  # no rotation
            else:  # 'all around'
                try:
                    scaled = pygame.transform.rotate(scaled, angle)
                except Exception:
                    pass

        # Position
        sx, sy = scratch_to_screen(sprite.x, sprite.y)
        rect = scaled.get_rect(center=(int(sx), int(sy)))
        self.screen.blit(scaled, rect)

    def _draw_costume(self, target: Target, is_stage: bool = False) -> None:
        if target.costume is None:
            return
        if target.costume.surface is None:
            _load_costume_surface(target.costume)
        if target.costume.surface is None:
            return
        base = target.costume.surface

        try:
            scaled = pygame.transform.scale(base, (WINDOW_W, WINDOW_H))
        except (ValueError, pygame.error):
            scaled = base
        self.screen.blit(scaled, (0, 0))

    def _draw_info(self) -> None:
        """Overlay: FPS, thread count, help."""
        font = pygame.font.Font(None, 24)
        threads = len([t for t in self.runtime.threads if not t.is_done()])
        fps = f'{self.clock.get_fps():.0f}'
        lines = [
            f'Threads: {threads}',
            f'FPS: {fps}',
            'ESC = Quit',
        ]
        y = 5
        for line in lines:
            img = font.render(line, True, COLOR_BLACK)
            self.screen.blit(img, (5, y))
            y += 22

    # ── Helpers for demo project construction ─────────────────────────

    @staticmethod
    def make_costume_surface(
        name: str,
        draw_fn: Callable[[pygame.Surface], Any],
        w: int = 80,
        h: int = 80,
    ) -> Costume:
        """Create a costume from a drawing function.
        ``draw_fn(surface)`` receives a pygame surface to draw on.
        """
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        draw_fn(surf)
        pygame.draw.rect(surf, (0, 0, 0, 255), surf.get_rect(), 2)
        cx, cy = w / 2, h / 2
        return Costume(
            name=name,
            data_format='pygame',
            bitmap_resolution=1,
            rotation_center_x=cx,
            rotation_center_y=cy,
            surface=surf,
        )
