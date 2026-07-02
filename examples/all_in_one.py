#!/usr/bin/env python3
"""All-in-one demo — replicates the full vm/demo.py project using the DSL.

Demonstrates every category: motion, looks, control, events, data,
operators, sensing, pen.

Usage::

    uv run python examples/all_in_one.py
"""

from __future__ import annotations

from scratch.dsl import Project, control, motion, pen

project = Project('All-in-One Demo')

# ── Stage ─────────────────────────────────────────────────────────────
project.stage.var('Score', 0)

# ── Sprite 1: Bouncing ball ───────────────────────────────────────────
ball = project.sprite('Ball')
ball.costume('ball')
ball.x = 0
ball.y = 100
ball.direction = 45

ball.when_flag_clicked(
    control.forever()(
        motion.move(5),
        motion.if_on_edge_bounce(),
        control.wait(0.01),
    ),
)

# ── Sprite 2: Square that follows a target ────────────────────────────
square = project.sprite('Square')
square.costume('square')
square.x = 100
square.y = 0
square.layer_order = 1

square.when_flag_clicked(
    control.forever()(
        motion.goto(x=100, y=0),
        control.wait(0.05),
    ),
)

# ── Sprite 3: Triangle that walks in a circle ─────────────────────────
tri = project.sprite('Triangle')
tri.costume('triangle')
tri.x = 0
tri.y = 0
tri.direction = 0
tri.layer_order = 2

tri.var('angle', 0.0)

tri.when_flag_clicked(
    control.forever()(
        motion.turn_right(3),
        motion.move(10),
        control.wait(0.02),
    ),
)

# ── Sprite 4: Pen writer ──────────────────────────────────────────────
writer = project.sprite('PenWriter')
writer.costume('pen')
writer.x = -200
writer.y = -150
writer.direction = 90
writer.layer_order = 3

writer.when_flag_clicked(
    pen.pen_clear(),
    pen.pen_down(),
    pen.pen_color('#0000FF'),
    control.forever()(
        motion.move(8),
        motion.if_on_edge_bounce(),
        motion.turn_right(2),
        control.wait(0.01),
    ),
)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save', '-o', type=str, help='Save project to .sb3 file')
    args = parser.parse_args()

    if args.save:
        project.save(args.save)
        print(f'Saved to {args.save}')
    else:
        rt = project.build_runtime()
        from scratch.vm.renderer import Renderer

        renderer = Renderer(rt, title=project.name)
        renderer.run()
