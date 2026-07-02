#!/usr/bin/env python3
"""Cat chase mouse — two sprites with variables and control flow.

The mouse chases the mouse pointer; the cat chases the mouse.
Uses variables, conditionals, and reporter nesting.

Usage::

    uv run python examples/cat_chase_mouse.py
"""

from __future__ import annotations

from scratch.dsl import Project, control, motion

project = Project("Cat Chase Mouse")

# ── Stage — declare global variables ──────────────────────────────────
project.stage.var("score", 0)

# ── Cat ───────────────────────────────────────────────────────────────
cat = project.sprite("Cat")
cat.costume("cat")
cat.x = -100
cat.y = 0
cat.direction = 90

cat.when_flag_clicked(
    control.forever()(
        motion.point_towards("Mouse"),
        motion.move(3),
        control.wait(0.03),
    ),
)

# ── Mouse ─────────────────────────────────────────────────────────────
mouse = project.sprite("Mouse")
mouse.costume("mouse")
mouse.x = 100
mouse.y = 0
mouse.direction = -90

mouse.when_flag_clicked(
    control.forever()(
        motion.move(2),
        motion.if_on_edge_bounce(),
        control.wait(0.03),
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

