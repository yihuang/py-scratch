"""
Renderer — pygame-based stage and sprite drawing.
"""

from __future__ import annotations

import io
import math
import re
from collections.abc import Callable
from typing import Any

import pygame
import resvg_py

from .constants import ROTATION_DONT_ROTATE, ROTATION_LEFT_RIGHT
from .runtime import Runtime
from .target import Target
from .types import Costume

# ── Constants ────────────────────────────────────────────────────────────

STAGE_W = 480
STAGE_H = 360
STAGE_SCALE: float = 2  # scale factor for the window (updated at runtime on Retina)

WINDOW_W = STAGE_W * STAGE_SCALE
WINDOW_H = STAGE_H * STAGE_SCALE

SCRATCH_TO_PYGAME = (STAGE_W // 2, STAGE_H // 2)

# Colours
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_GREY = (200, 200, 200)
COLOR_STAGE_BG = (220, 220, 220)

# ── Speech bubble style ────────────────────────────────────────────


class BubbleStyle:
    """Speech/think bubble style constants (from scratch-render TextBubbleSkin.js)."""

    MAX_LINE_WIDTH = 170  # Scratch pixels
    MIN_WIDTH = 50
    STROKE_WIDTH = 4
    PADDING = 10
    CORNER_RADIUS = 16
    TAIL_HEIGHT = 12
    FONT_SIZE = 14
    LINE_HEIGHT = 16
    FONT_COLOR = (87, 94, 117)  # #575E75
    BUBBLE_FILL = (255, 255, 255)  # white
    BUBBLE_STROKE = (0, 0, 0, 38)  # rgba(0,0,0,0.15)
    _TAIL_BEZIER_SAY: list[tuple[float, float]] = [
        (0, 4),
        (4, 8),
        (4, 10),
        (2, 12),
        (-1, 12),
        (-11, 8),
        (-16, 0),
    ]


# Keyboard mapping — Scratch key names → pygame key codes
KEY_MAP: dict[str, int] = {
    "space": pygame.K_SPACE,
    "left arrow": pygame.K_LEFT,
    "right arrow": pygame.K_RIGHT,
    "up arrow": pygame.K_UP,
    "down arrow": pygame.K_DOWN,
    "enter": pygame.K_RETURN,
    "a": pygame.K_a,
    "b": pygame.K_b,
    "c": pygame.K_c,
    "d": pygame.K_d,
    "e": pygame.K_e,
    "f": pygame.K_f,
    "g": pygame.K_g,
    "h": pygame.K_h,
    "i": pygame.K_i,
    "j": pygame.K_j,
    "k": pygame.K_k,
    "l": pygame.K_l,
    "m": pygame.K_m,
    "n": pygame.K_n,
    "o": pygame.K_o,
    "p": pygame.K_p,
    "q": pygame.K_q,
    "r": pygame.K_r,
    "s": pygame.K_s,
    "t": pygame.K_t,
    "u": pygame.K_u,
    "v": pygame.K_v,
    "w": pygame.K_w,
    "x": pygame.K_x,
    "y": pygame.K_y,
    "z": pygame.K_z,
    "0": pygame.K_0,
    "1": pygame.K_1,
    "2": pygame.K_2,
    "3": pygame.K_3,
    "4": pygame.K_4,
    "5": pygame.K_5,
    "6": pygame.K_6,
    "7": pygame.K_7,
    "8": pygame.K_8,
    "9": pygame.K_9,
}

# Reverse: pygame key code → Scratch key name
KEY_CODE_TO_NAME: dict[int, str] = {code: name for name, code in KEY_MAP.items()}


def scratch_to_screen(x: float, y: float) -> tuple[float, float]:
    """Convert Scratch coordinates to screen coordinates.

    Scratch: origin at centre, +x right, +y up.
    Screen: origin at top-left, +x right, +y down.

    Infinity/NaN values are clamped to the stage boundary to prevent
    ``OverflowError`` in pygame drawing functions.
    """
    sx = (x + STAGE_W / 2) * STAGE_SCALE
    sy = (STAGE_H / 2 - y) * STAGE_SCALE
    if not math.isfinite(sx):
        sx = 0.0 if math.isnan(sx) else (float("inf") if sx > 0 else float("-inf"))
        sx = _clamp_screen(sx, STAGE_W * STAGE_SCALE)
    if not math.isfinite(sy):
        sy = 0.0 if math.isnan(sy) else (float("inf") if sy > 0 else float("-inf"))
        sy = _clamp_screen(sy, STAGE_H * STAGE_SCALE)
    return sx, sy


def _clamp_screen(v: float, limit: float) -> float:
    """Clamp a screen coordinate to a finite range."""
    if not math.isfinite(v):
        return limit if v > 0 else -limit
    return v


# ── Costume loading ──────────────────────────────────────────────────────


def _render_svg_data(data: bytes) -> pygame.Surface:
    """Render SVG bytes to a pygame surface.

    Uses **resvg_py** (resvg Rust library) for fast, high-fidelity
    SVG rasterization.
    """
    try:
        svg_text = data.decode("utf-8")
        png_data = resvg_py.svg_to_bytes(svg_string=svg_text)
    except ValueError:
        # return placeholder for zero sized svg
        surf = pygame.Surface((1, 1), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        return surf
    return pygame.image.load(io.BytesIO(png_data))


def _adjust_rotation_centre(costume: Costume, data: bytes, surf: pygame.Surface) -> None:
    """Adjust rotation centre for fractional SVG dimensions.

    pygame surfaces use integer pixel sizes, but SVG dimensions can be
    fractional (e.g. 87.424\u00d714).  Scale the stored rotation centre
    to match the actual rendered surface size.
    """
    text = data.decode("utf-8", errors="replace")
    w = re.search(r'width="([\d.]+)"', text)
    h = re.search(r'height="([\d.]+)"', text)
    nom_w = float(w.group(1)) if w else 0.0
    nom_h = float(h.group(1)) if h else 0.0
    if nom_w <= 0 or nom_h <= 0:
        return
    sw, sh = surf.get_size()
    if sw <= 0 or sh <= 0:
        return
    if sw != nom_w or sh != nom_h:
        costume.rotation_center_x *= sw / nom_w
        costume.rotation_center_y *= sh / nom_h


def _load_costume_surface(costume: Costume) -> pygame.Surface | None:
    """Return a pygame surface for *costume*, loading lazily if needed.

    All costume types (SVG, PNG, JPG, …) are loaded on first access instead
    of during ``load_assets``.  Handles embedded ``<image>`` data URIs in
    SVGs which pygame's built-in renderer does not support.

    Returns ``None`` when no surface can be produced.
    """
    if costume.surface is not None:
        surf = costume.surface
        assert isinstance(surf, pygame.Surface)
        return surf

    if not costume.data:
        return None

    if costume.data_format == "svg":
        surf = _render_svg_data(costume.data)
        _adjust_rotation_centre(costume, costume.data, surf)
    else:
        surf = pygame.image.load(io.BytesIO(costume.data))

    costume.surface = surf
    return surf


# ── Pen layer cache ──────────────────────────────────────────────────────


class PenLayer:
    """Manages a persistent surface for pen strokes."""

    def __init__(self) -> None:
        self.surface = pygame.Surface(
            (int(STAGE_W * STAGE_SCALE), int(STAGE_H * STAGE_SCALE)),
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

    def __init__(self, runtime: Runtime, title: str = "Scratch VM") -> None:
        self.runtime = runtime
        self.title = title

        pygame.init()

        # We'll update these module globals once we know the actual pixel ratio.
        global STAGE_SCALE, WINDOW_W, WINDOW_H

        # SCALED flag lets SDL2 create the framebuffer at the OS's native pixel
        # resolution (e.g. 2x on Retina displays), keeping the window at the
        # requested logical size.  We then compute the actual pixel scale from
        # the surface size so all drawing stays crisp on high-DPI screens.
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.SCALED)
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()

        # Actual surface size (may be larger than requested on Retina displays)
        self._surf_w = self.screen.get_width()
        self._surf_h = self.screen.get_height()
        self._pixel_scale = self._surf_w / STAGE_W  # actual pixels per Scratch unit
        self._logical_scale = STAGE_SCALE  # the original 2x (960x540 window points)
        STAGE_SCALE = self._pixel_scale
        WINDOW_W = self._surf_w
        WINDOW_H = self._surf_h

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
        self.runtime.set_keyboard_state(pressed)

    # ── Mouse state bridge ────────────────────────────────────────────

    def _sync_mouse(self) -> None:
        self.runtime.set_mouse_position(self._mouse_x, self._mouse_y)
        self.runtime.set_mouse_down(self._mouse_down)

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
                    self._mouse_x = px / self._logical_scale - STAGE_W / 2
                    self._mouse_y = -(py / self._logical_scale) + STAGE_H / 2
                case pygame.MOUSEBUTTONDOWN:
                    px, py = event.pos
                    self._mouse_x = px / self._logical_scale - STAGE_W / 2
                    self._mouse_y = -(py / self._logical_scale) + STAGE_H / 2
                    self._mouse_down = True
                    self.runtime.start_click_hat(self._mouse_x, self._mouse_y)
                case pygame.MOUSEBUTTONUP:
                    self._mouse_down = False

    def _update(self) -> None:
        """Step the runtime and update pen state."""
        # Check for pen clear requests
        if self.runtime.stage and getattr(self.runtime.stage, "_pen_clear_requested", False):
            self.pen_layer.clear()
            self.runtime.stage._pen_clear_requested = False

        # Handle stamp requests
        stamps = []
        if self.runtime.stage and hasattr(self.runtime.stage, "_stamp_queue"):
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

        # Pen drawing: after each step, draw lines for any sprite that moved
        # while pen_down is True (matching official Scratch behaviour).
        for t in self.runtime.sprite_targets():
            if not t.pen_down:
                t._pen_prev_x = None
                t._pen_prev_y = None
                continue
            if t._pen_prev_x is not None and t._pen_prev_y is not None:
                if t._pen_prev_x != t.x or t._pen_prev_y != t.y:
                    self.pen_layer.draw_line(
                        t._pen_prev_x,
                        t._pen_prev_y,
                        t.x,
                        t.y,
                        t.pen_color,
                        t.pen_size,
                    )
            t._pen_prev_x = t.x
            t._pen_prev_y = t.y
        # Clear expired say/think bubbles
        tick = self.runtime.clock.tick_count
        for t in self.runtime.sprite_targets():
            if t.say_until is not None and tick >= t.say_until:
                t.say_text = None
                t.say_until = None

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

        # Draw pen layer (behind sprites, matching Scratch behaviour)
        self.screen.blit(self.pen_layer.surface, (0, 0))

        # Draw sprite layers (sorted by layer_order), on top of pen
        sprites = sorted(self.runtime.sprite_targets(), key=lambda t: t.layer_order)
        for sprite in sprites:
            if not sprite.visible:
                continue
            self._draw_sprite(sprite)
            self._draw_bubble(sprite)

        # Draw overlay info
        self._draw_info()

        pygame.display.flip()

    def _draw_sprite(self, sprite: Target) -> None:
        """Draw a sprite at its position with rotation and size.

        Matches official Scratch rendering pipeline:
        - Skin size = texture pixels / bitmap_resolution (in Scratch units)
        - Rendered size = skin_size * (size/100) * STAGE_SCALE (screen pixels)
        - Rotation and scaling combined in one pass via ``rotozoom`` for less aliasing.
        """
        if not sprite.costume:
            return  # no costume — nothing to draw

        costume = sprite.costume
        if costume.surface is None:
            _load_costume_surface(costume)

        if costume.surface is None:
            return  # could not load the surface

        base = costume.surface

        # Skin size = texture pixels / bitmap_resolution
        # e.g. 100x100 image with resolution=2 => skin is 50x50 Scratch units
        resolution = costume.bitmap_resolution or 1

        # Scratch: 0=up, 90=right. Costumes are designed facing right.
        # pygame rotates counter-clockwise (same as rotozoom).
        angle = 90 - sprite.direction

        # Combined scale: sprite size % + convert Scratch units → screen pixels
        render_scale = (sprite.size / 100.0) * STAGE_SCALE / resolution

        if sprite.rotation_style == ROTATION_DONT_ROTATE:
            # No rotation — just scale
            w = max(1, int(base.get_width() * render_scale))
            h = max(1, int(base.get_height() * render_scale))
            try:
                scaled = pygame.transform.smoothscale(base, (w, h))
            except (ValueError, pygame.error):
                scaled = base

        elif sprite.rotation_style == ROTATION_LEFT_RIGHT and (
            sprite.direction > 90 or sprite.direction < -90
        ):
            # Flip horizontally (no rotation)
            scaled = pygame.transform.rotozoom(base, 0, render_scale)
            scaled = pygame.transform.flip(scaled, True, False)

        else:
            # 'all around' — rotate & scale in one pass for less aliasing
            scaled = pygame.transform.rotozoom(base, angle, render_scale)

        # Position (scratch_to_screen already includes STAGE_SCALE)
        sx, sy = scratch_to_screen(sprite.x, sprite.y)

        # Apply rotation center offset so the costume's rotation centre
        # aligns with the sprite's (x, y) position.
        #
        # ``rotozoom`` rotates around the SURFACE CENTER, so the offset
        # must be computed relative to the centre, not the top-left.
        sw, sh = scaled.get_size()
        cx = costume.rotation_center_x * render_scale
        cy = costume.rotation_center_y * render_scale
        if angle != 0 and sprite.rotation_style not in (ROTATION_DONT_ROTATE,):
            a = math.radians(angle)
            cos_a = math.cos(a)
            sin_a = math.sin(a)
            # ``cx``, ``cy`` are in the pre-rotation coordinate system (scaled
            # but not yet rotated).  Compute the offset from the pre-rotation
            # image centre, then rotate that offset.
            #
            # pygame uses a y-down coordinate system, but the standard rotation
            # formula assumes y-up.  The sign of the y-terms is flipped:
            #   y-up:      ox = cx*cos - cy*sin,  oy = cx*sin + cy*cos
            #   y-down:    ox = cx*cos + cy*sin,  oy = -cx*sin + cy*cos
            orig_w = base.get_width() * render_scale
            orig_h = base.get_height() * render_scale
            dx = cx - orig_w / 2.0
            dy = cy - orig_h / 2.0
            ox = sw / 2.0 + dx * cos_a + dy * sin_a
            oy = sh / 2.0 - dx * sin_a + dy * cos_a
        else:
            ox = cx
            oy = cy

        rect = scaled.get_rect()
        # Guard against infinity/NaN positions (e.g. from div-by-zero)
        if not (math.isfinite(sx) and math.isfinite(sy)):
            return
        rect.x = int(round(sx - ox))
        rect.y = int(round(sy - oy))
        self.screen.blit(scaled, rect)

    # ── Speech bubble drawing ─────────────────────────────────────────

    def _draw_bubble(self, sprite: Target) -> None:
        """Draw the speech/think bubble for a sprite, if ``say_text`` is set."""
        text = sprite.say_text
        if not text:
            return

        scale = STAGE_SCALE
        scaled_font_size = int(BubbleStyle.FONT_SIZE * scale)
        font = pygame.font.Font(None, scaled_font_size)
        lines = self._wrap_text(font, text)

        # Measure longest line (in screen pixels at scale)
        max_line_w = max(font.size(line)[0] for line in lines)

        # Bubble dimensions in Scratch coords
        max_line_w_scratch = int(max_line_w / scale)
        padded_w = max(max_line_w_scratch, BubbleStyle.MIN_WIDTH) + BubbleStyle.PADDING * 2
        padded_h = BubbleStyle.LINE_HEIGHT * len(lines) + BubbleStyle.PADDING * 2

        # Total size including stroke and tail
        total_w = padded_w + BubbleStyle.STROKE_WIDTH
        total_h = padded_h + BubbleStyle.STROKE_WIDTH + BubbleStyle.TAIL_HEIGHT

        # Position above the sprite, centred horizontally
        points_left = sprite.x > 0
        bubble_scratch_y = sprite.y + BUBBLE_Y_OFFSET + total_h / 2

        bx, by = scratch_to_screen(sprite.x, bubble_scratch_y)

        # Create a surface for the bubble at screen resolution
        surf_w = int(total_w * scale)
        surf_h = int(total_h * scale)
        bubble_surf = pygame.Surface((surf_w, surf_h), pygame.SRCALPHA)

        # Draw the bubble
        self._render_bubble_surface(
            bubble_surf, lines, padded_w, padded_h, total_w, total_h, scale, points_left
        )

        # Blit at calculated screen position
        blit_x = int(bx - total_w * scale / 2)
        blit_y = int(by - total_h * scale / 2)
        self.screen.blit(bubble_surf, (blit_x, blit_y))

    @staticmethod
    def _wrap_text(font: pygame.font.Font, text: str) -> list[str]:
        """Wrap text to fit within MAX_LINE_WIDTH Scratch pixels."""
        lines: list[str] = []
        for paragraph in text.split("\n"):
            words = paragraph.split(" ")
            current = ""
            for word in words:
                test = current + (" " if current else "") + word
                w, _ = font.size(test)
                if w > BubbleStyle.MAX_LINE_WIDTH * STAGE_SCALE and current:
                    lines.append(current)
                    current = word
                else:
                    current = test
            if current:
                lines.append(current)
        return lines if lines else [""]

    @staticmethod
    def _render_bubble_surface(
        surf: pygame.Surface,
        lines: list[str],
        padded_w: int,
        padded_h: int,
        total_w: int,
        total_h: int,
        scale: float,
        points_left: bool,
    ) -> None:
        """Render the bubble shape and text onto *surf* at the given scale."""
        s = int(scale)  # short alias — int for pygame API calls
        # Scale bubble coordinates to surface pixels
        R = BubbleStyle.CORNER_RADIUS * s
        P = BubbleStyle.PADDING * s
        SW = BubbleStyle.STROKE_WIDTH * s
        BubbleStyle.TAIL_HEIGHT * s
        pw = padded_w * s
        ph = padded_h * s

        # Rounded rectangle path
        points: list[tuple[float, float]] = []
        # Top edge (left → right)
        points.append((R, 0))
        points.append((pw - R, 0))
        # Top-right corner
        points.append((pw, 0))
        points.append((pw, R))
        # Right edge
        points.append((pw, ph - R))
        # Bottom-right corner
        points.append((pw, ph))
        points.append((pw - R, ph))
        # Bottom edge
        pw - R
        # Tail position: right side, above the corner
        tail_x = pw
        tail_y = ph

        # Mirror for points_left
        if points_left:
            for i, (px, py) in enumerate(points):
                points[i] = (pw - px, py)
            tail_x = 0

        # Build rects for rounded corners using antialiased circles
        rect = pygame.Rect(0, 0, pw, ph)
        # Draw filled rounded rect
        color = BubbleStyle.BUBBLE_FILL

        # Use pygame's built-in rounded rect via gfxdraw or manual circles
        # Fill body
        body_rect = pygame.Rect(R, 0, pw - 2 * R, ph)
        pygame.draw.rect(surf, color, body_rect)

        # Fill top/bottom strips
        top_rect = pygame.Rect(0, R, pw, ph - 2 * R)
        pygame.draw.rect(surf, color, top_rect)

        # Draw corners as filled circles
        for cx, cy in [(R, R), (pw - R, R), (R, ph - R), (pw - R, ph - R)]:
            pygame.draw.circle(surf, color, (cx, cy), R)

        # Draw tail
        if points_left:
            # Flip the tail horizontally
            tail_points = [
                (tail_x, tail_y + 0 * s),
                (tail_x + 4 * s, tail_y + 4 * s),
                (tail_x + 4 * s, tail_y + 10 * s),
                (tail_x + 2 * s, tail_y + 12 * s),
                (tail_x - 1 * s, tail_y + 12 * s),
                (tail_x - 11 * s, tail_y + 8 * s),
                (tail_x - 16 * s, tail_y + 0 * s),
            ]
        else:
            tail_points = [
                (tail_x, tail_y),
                (tail_x - 4 * s, tail_y + 4 * s),
                (tail_x - 4 * s, tail_y + 10 * s),
                (tail_x - 2 * s, tail_y + 12 * s),
                (tail_x + 1 * s, tail_y + 12 * s),
                (tail_x + 11 * s, tail_y + 8 * s),
                (tail_x + 16 * s, tail_y),
            ]
        pygame.draw.polygon(surf, color, tail_points)

        # Stroke
        stroke_color = (0, 0, 0, 38)
        # For simplicity, draw an outline rect and tail with thin line
        pygame.draw.rect(surf, stroke_color, rect, SW)
        pygame.draw.polygon(surf, stroke_color, tail_points, SW)

        # Draw text at scaled font size
        font_size = max(1, int(BubbleStyle.FONT_SIZE * s))
        text_font = pygame.font.Font(None, font_size)
        for i, line in enumerate(lines):
            text_surf = text_font.render(line, True, BubbleStyle.FONT_COLOR)
            tx = int(P + SW // 2)
            ty = int(P + SW // 2 + BubbleStyle.LINE_HEIGHT * i * s / STAGE_SCALE)
            surf.blit(text_surf, (tx, ty))

    def _draw_costume(self, target: Target, is_stage: bool = False) -> None:
        """Draw a costume (backdrop) at its actual skin size, centered on stage.

        Matches official Scratch behavior: renders at ``texture_size / bitmap_resolution``,
        *not* stretched to fill the window.
        """
        if target.costume is None:
            return
        if target.costume.surface is None:
            _load_costume_surface(target.costume)
        if target.costume.surface is None:
            return
        base = target.costume.surface

        # Skin size = texture pixels / bitmap_resolution
        # e.g. 100x100 image with resolution=2 => skin is 50x50 Scratch units
        resolution = target.costume.bitmap_resolution or 1
        skin_w = base.get_width() / resolution
        skin_h = base.get_height() / resolution

        # Convert to screen pixels
        screen_w = max(1, int(skin_w * STAGE_SCALE))
        screen_h = max(1, int(skin_h * STAGE_SCALE))

        try:
            scaled = pygame.transform.smoothscale(base, (screen_w, screen_h))
        except (ValueError, pygame.error):
            scaled = base

        # Center at stage origin (Scratch 0,0 => screen center)
        sx = WINDOW_W // 2
        sy = WINDOW_H // 2
        rect = scaled.get_rect(center=(sx, sy))
        self.screen.blit(scaled, rect)

    def _draw_info(self) -> None:
        """Overlay: FPS, thread count, help."""
        font = pygame.font.Font(None, OVERLAY_FONT_SIZE)
        threads = len([t for t in self.runtime.threads if not t.is_done()])
        fps = f"{self.clock.get_fps():.0f}"
        lines = [
            f"Threads: {threads}",
            f"FPS: {fps}",
            "ESC = Quit",
        ]
        y = OVERLAY_Y
        for line in lines:
            img = font.render(line, True, COLOR_BLACK)
            self.screen.blit(img, (OVERLAY_X, y))
            y += OVERLAY_LINE_HEIGHT

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
            data_format="pygame",
            bitmap_resolution=1,
            rotation_center_x=cx,
            rotation_center_y=cy,
            surface=surf,
        )


# Overlay / debug info
OVERLAY_FONT_SIZE = 24
OVERLAY_X = 5
OVERLAY_Y = 5
OVERLAY_LINE_HEIGHT = 22

# Bubble position
BUBBLE_Y_OFFSET = 60
