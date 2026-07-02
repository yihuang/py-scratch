#!/usr/bin/env python3
"""Calculator — demonstrates reporter nesting and operators.

Builds a project that shows how arithmetic and string operators compose,
including nesting reporters inside other blocks' inputs.

Usage::

    uv run python examples/calculator.py
"""

from __future__ import annotations

from scratch.dsl import Project, control, data, motion, operators

project = Project("Calculator")

# ── Sprite with variables for operands ────────────────────────────────
sprite = project.sprite("Calc")
sprite.costume("ball")
sprite.var("a", 10)
sprite.var("b", 3)
sprite.var("result", 0)

# On green flag, compute some expressions using reporter nesting.
# Each data.variable("a") creates a reporter block that reads the
# variable at runtime.  operators.add(...) wraps them in an operator
# reporter.  The outermost data.set_variable uses the add reporter
# as its VALUE input.
sprite.when_flag_clicked(
    # result = a + b  (reporter nesting)
    data.set_variable("result", operators.add(data.variable("a"), data.variable("b"))),
    # Move to keep the sprite animated
    control.forever()(
        motion.move(3),
        motion.if_on_edge_bounce(),
        control.wait(0.05),
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

