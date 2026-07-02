#!/usr/bin/env python3
"""Bouncing ball — a single sprite that bounces around the stage.

Usage::

    uv run python examples/bouncing_ball.py
"""

from __future__ import annotations

from scratch.dsl import Project, control, motion

project = Project('Bouncing Ball')
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
