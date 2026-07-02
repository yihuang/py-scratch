#!/usr/bin/env python3
"""Mouse follower — a sprite that follows the mouse pointer.

Usage::

    uv run python examples/mouse_follower.py
"""

from __future__ import annotations

from scratch.dsl import Project, control, motion

project = Project('Mouse Follower')
square = project.sprite('Square')

square.costume('square')
square.x = 100
square.y = 0
square.layer_order = 1

# The runtime doesn't have active mouse-tracking reporters wired
# into the DSL reporters yet, so this uses static positions.
# Once the runtime supports sensing_mousex/y, replace with:
#   motion.goto(x=sensing.mouse_x(), y=sensing.mouse_y())
square.when_flag_clicked(
    control.forever()(
        motion.goto(x=100, y=0),  # static target for now
        control.wait(0.05),
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
