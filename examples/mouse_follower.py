#!/usr/bin/env python3
"""Mouse follower — a sprite that follows the mouse pointer.

Usage::

    uv run python examples/mouse_follower.py
"""

from __future__ import annotations

from pathlib import Path

from scratch.dsl import Project, control, motion

project = Project("Mouse Follower", assets_dir=Path(__file__).parent)

square = project.sprite("Follower")
square.costume("square", "square.svg")
square.x = 0
square.y = 0

square.when_flag_clicked(
    control.forever()(
        motion.point_towards("_mouse_"),
        motion.move(5),
        control.wait(0.02),
    ),
)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", "-o", type=str, help="Save project to .sb3 file")
    args = parser.parse_args()

    if args.save:
        project.save(args.save)
        print(f"Saved to {args.save}")
    else:
        rt = project.build_runtime()
        from scratch.vm.renderer import Renderer

        renderer = Renderer(rt, title=project.name)
        renderer.run()
