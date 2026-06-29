#!/usr/bin/env python3
"""
Demo — a sample Scratch project with motion, pen, and control blocks.

Run::
    python3 -m scratch.vm           # as a module
    python3 scratch/vm/demo.py      # directly
"""

from __future__ import annotations

import pygame

from scratch.vm import Block, Runtime, Target, Variable, make_block
from scratch.vm.opcodes import OPCODE_MAP
from scratch.vm.renderer import (
    Renderer,
)
from scratch.vm.types import Costume

# ── Placeholder costume helpers ──────────────────────────────────────────


def _circle_costume(name: str, color: tuple[int, ...], r: int = 35) -> Costume:
    surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
    center = (r, r)
    pygame.draw.circle(surf, color, center, r)
    pygame.draw.circle(surf, (0, 0, 0), center, r, 2)
    return Costume(
        name=name,
        data_format='pygame',
        bitmap_resolution=1,
        rotation_center_x=r,
        rotation_center_y=r,
        surface=surf,
    )


def _rect_costume(name: str, color: tuple[int, ...], w: int = 60, h: int = 40) -> Costume:
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    surf.fill(color)
    pygame.draw.rect(surf, (0, 0, 0), surf.get_rect(), 2)
    return Costume(
        name=name,
        data_format='pygame',
        bitmap_resolution=1,
        rotation_center_x=w / 2,
        rotation_center_y=h / 2,
        surface=surf,
    )


def _triangle_costume(name: str, color: tuple[int, ...], size: int = 40) -> Costume:
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    points = [(size / 2, 0), (0, size), (size, size)]
    pygame.draw.polygon(surf, color, points)
    pygame.draw.polygon(surf, (0, 0, 0), points, 2)
    return Costume(
        name=name,
        data_format='pygame',
        bitmap_resolution=1,
        rotation_center_x=size / 2,
        rotation_center_y=size / 2,
        surface=surf,
    )


# ── Project builder ──────────────────────────────────────────────────────


def build_demo_project() -> Runtime:
    """Construct a Runtime with sprites, blocks, and scripts."""
    rt = Runtime()
    rt.register_all(OPCODE_MAP)

    # ── Stage ─────────────────────────────────────────────────────────
    stage = Target(name='Stage', is_stage=True)
    stage.costumes = [_circle_costume('default', (200, 220, 255, 255), 240)]
    # Stage doesn't use position/direction — costumes fill the backdrop.
    # Variables shared across sprites should go on stage.
    stage.variables['score'] = Variable('Score', 0)
    rt.add_target(stage)

    # ── Sprite 1: Bouncing ball ───────────────────────────────────────
    ball = Target(name='Ball')
    ball.costumes = [_circle_costume('ball', (255, 50, 50))]
    ball.x = 0
    ball.y = 100
    ball.direction = 45

    # Blocks:
    #   when flag clicked
    #   forever:
    #     move 5 steps
    #     if on edge, bounce
    #     wait 0.01

    ball.blocks = {
        'hat1': make_block('event_whenflagclicked', 'hat1', top_level=True, next_='rep1'),
        'rep1': make_block('control_forever', 'rep1', parent='hat1', inputs={'SUBSTACK': 'stack1'}),
        'stack1': Block(
            id='stack1',
            opcode='motion_movesteps',
            parent='rep1',
            inputs={'STEPS': 5},
            next='bounce1',
        ),
        'bounce1': Block(id='bounce1', opcode='motion_ifonedgebounce', parent='rep1', next='wait1'),
        'wait1': Block(id='wait1', opcode='control_wait', parent='rep1', inputs={'DURATION': 0.01}),
    }
    ball._rebuild_hat_cache()
    rt.add_target(ball)

    # ── Sprite 2: Square that follows the mouse ───────────────────────
    square = Target(name='Square')
    square.costumes = [_rect_costume('square', (50, 150, 50))]
    square.x = 100
    square.y = 0
    square.layer_order = 1

    square.blocks = {
        'hat2': make_block('event_whenflagclicked', 'hat2', top_level=True, next_='rep2'),
        'rep2': make_block('control_forever', 'rep2', parent='hat2', inputs={'SUBSTACK': 'goto1'}),
        'goto1': Block(
            id='goto1',
            opcode='motion_gotoxy',
            parent='rep2',
            inputs={
                'X': 100,  # static position
                'Y': 0,
            },
            next='wait2',
        ),
        'wait2': Block(id='wait2', opcode='control_wait', parent='rep2', inputs={'DURATION': 0.05}),
    }
    square._rebuild_hat_cache()
    rt.add_target(square)

    # ── Sprite 3: Triangle that walks in a circle ─────────────────────
    tri = Target(name='Triangle')
    tri.costumes = [_triangle_costume('tri', (200, 50, 200))]
    tri.x = 0
    tri.y = 0
    tri.direction = 0
    tri.layer_order = 2

    # Create a variable on the target
    tri.variables['angle'] = Variable('angle', 0.0)

    tri.blocks = {
        'hat3': make_block('event_whenflagclicked', 'hat3', top_level=True, next_='rep3'),
        'rep3': make_block('control_forever', 'rep3', parent='hat3', inputs={'SUBSTACK': 'turn3'}),
        'turn3': Block(
            id='turn3',
            opcode='motion_turnright',
            parent='rep3',
            inputs={'DEGREES': 3},
            next='step3',
        ),
        'step3': Block(
            id='step3', opcode='motion_movesteps', parent='rep3', inputs={'STEPS': 10}, next='wait3'
        ),
        'wait3': Block(id='wait3', opcode='control_wait', parent='rep3', inputs={'DURATION': 0.02}),
    }
    tri._rebuild_hat_cache()
    rt.add_target(tri)

    # ── Sprite 4: Pen writer ─────────────────────────────────────────
    pen = Target(name='PenWriter')
    pen.costumes = [_circle_costume('pen', (0, 0, 255), 8)]
    pen.x = -200
    pen.y = -150
    pen.direction = 90
    pen.layer_order = 3

    pen.blocks = {
        'hat4': make_block('event_whenflagclicked', 'hat4', top_level=True, next_='pen_clear1'),
        'pen_clear1': Block(id='pen_clear1', opcode='pen_clear', parent='hat4', next='pen_down1'),
        'pen_down1': Block(id='pen_down1', opcode='pen_penDown', parent='hat4', next='pen_color1'),
        'pen_color1': Block(
            id='pen_color1',
            opcode='pen_setPenColorToColor',
            parent='hat4',
            inputs={'COLOR': 0x0000FF},
            next='rep4',
        ),
        'rep4': make_block(
            'control_forever', 'rep4', parent='hat4', inputs={'SUBSTACK': 'move_pen'}
        ),
        'move_pen': Block(
            id='move_pen',
            opcode='motion_movesteps',
            parent='rep4',
            inputs={'STEPS': 8},
            next='bounce_pen',
        ),
        'bounce_pen': Block(
            id='bounce_pen', opcode='motion_ifonedgebounce', parent='rep4', next='turn_pen'
        ),
        'turn_pen': Block(
            id='turn_pen',
            opcode='motion_turnright',
            parent='rep4',
            inputs={'DEGREES': 2},
            next='wait_pen',
        ),
        'wait_pen': Block(
            id='wait_pen', opcode='control_wait', parent='rep4', inputs={'DURATION': 0.01}
        ),
    }
    pen._rebuild_hat_cache()
    rt.add_target(pen)

    return rt


# ── Entry point ──────────────────────────────────────────────────────────


def main() -> None:
    rt = build_demo_project()
    renderer = Renderer(rt, title='Scratch VM — Demo')
    renderer.run()


if __name__ == '__main__':
    main()
