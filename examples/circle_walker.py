#!/usr/bin/env python3
"""Circle walker — a sprite that walks in a circle.

Uses variables to track angle and control the turn radius.

Usage::

    uv run python examples/circle_walker.py
"""

from __future__ import annotations

from scratch.dsl import Project, control, motion

project = Project('Circle Walker')
tri = project.sprite('Triangle')

tri.costume('triangle')
tri.x = 0
tri.y = 0
tri.direction = 0
tri.layer_order = 2

# Declare a variable to track the turning angle
tri.var('angle', 0.0)

tri.when_flag_clicked(
    control.forever()(
        motion.turn_right(3),
        motion.move(10),
        control.wait(0.02),
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
