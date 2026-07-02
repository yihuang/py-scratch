#!/usr/bin/env python3
"""Pen artist — a pen-enabled sprite that draws as it moves.

Usage::

    uv run python examples/pen_artist.py
"""

from __future__ import annotations

from scratch.dsl import Project, control, motion, pen

project = Project('Pen Artist')
writer = project.sprite('PenWriter')

writer.costume('pen')
writer.x = -200
writer.y = -150
writer.direction = 90
writer.layer_order = 3

writer.when_flag_clicked(
    pen.pen_clear(),  # not a valid call in __init__: these are register calls
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
