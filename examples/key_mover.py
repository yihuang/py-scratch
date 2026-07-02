#!/usr/bin/env python3
"""Key mover — move a sprite with arrow keys, with a score counter.

Demonstrates:
  - Multiple scripts per sprite
  - Hat blocks (when_flag_clicked, when_key_pressed)
  - Variable usage (score)
  - C-shaped blocks (if_)
  - Nesting reporters

Usage::

    uv run python examples/key_mover.py
"""

from __future__ import annotations

from scratch.dsl import Project, data, looks, motion, operators

project = Project("Key Mover")
player = project.sprite("Player")

player.costume("ball")
player.x = 0
player.y = 0
player.var("score", 0)

# Move with arrow keys
player.when_key_pressed("right")(motion.change_x(10))
player.when_key_pressed("left")(motion.change_x(-10))
player.when_key_pressed("up")(motion.change_y(10))
player.when_key_pressed("down")(motion.change_y(-10))

# Score on green flag: increment score every time space is pressed
player.when_key_pressed("space")(
    data.set_variable("score", operators.add(data.variable("score"), 1)),
    looks.say(operators.join("Score: ", data.variable("score"))),
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

