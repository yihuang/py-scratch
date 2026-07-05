#!/usr/bin/env python3
"""
Procedures demo — custom blocks (My Blocks) in the DSL.

Defines reusable dance-move procedures with parameters, then calls them
from sprite scripts.  Movement is animated — steps and spins happen in
small increments with ``wait`` between each frame.

Usage::

    uv run python examples/procedures_demo.py
"""

from __future__ import annotations

from pathlib import Path

from scratch.dsl import (
    Project,
    control,
    data,
    looks,
    motion,
    operators,
    procedures,
)

project = Project('Dance Party', assets_dir=Path(__file__).parent)
stage = project.stage

# ── Stage setup ──────────────────────────────────────────────────────────

stage.var('beat', 0.5)

stage.when_flag_clicked(
    data.set_variable('beat', 0.5),
)

# ── Dancer sprite ────────────────────────────────────────────────────────

sprite = project.sprite('Dancer')
sprite.costume('cat', 'cat.svg')

# ── Custom block definitions ─────────────────────────────────────────────
#
# ``sprite.define(proccode, *param_names)`` creates a top-level hat block
# and returns a callable that attaches the body.

STEP_SIZE = 5

sprite.define('step %s %n', 'dir', 'px')(
    control.repeat(operators.div(procedures.arg('px'), STEP_SIZE))(
        control.if_(operators.eq(procedures.arg('dir'), 'right'))(
            motion.change_x(STEP_SIZE),
        ),
        control.if_(operators.eq(procedures.arg('dir'), 'left'))(
            motion.change_x(operators.mult(STEP_SIZE, -1)),
        ),
        control.if_(operators.eq(procedures.arg('dir'), 'up'))(
            motion.change_y(STEP_SIZE),
        ),
        control.if_(operators.eq(procedures.arg('dir'), 'down'))(
            motion.change_y(operators.mult(STEP_SIZE, -1)),
        ),
        control.wait(0.03),
    ),
)

SPIN_STEP = 15

sprite.define('spin %n', 'deg')(
    control.repeat(operators.div(procedures.arg('deg'), SPIN_STEP))(
        motion.turn_right(SPIN_STEP),
        control.wait(0.03),
    ),
)

# ── Calling the custom blocks ────────────────────────────────────────────

sprite.when_flag_clicked(
    procedures.call('step %s %n', 'right', 50),
    procedures.call('step %s %n', 'up', 30),
    procedures.call('spin %n', 360),
    control.wait(data.variable('beat')),
    procedures.call('step %s %n', 'left', 80),
    procedures.call('step %s %n', 'down', 30),
    procedures.call('spin %n', -180),
    control.wait(data.variable('beat')),
    procedures.call('step %s %n', 'right', 50),
    procedures.call('step %s %n', 'up', 30),
    procedures.call('spin %n', 360),
    control.wait(data.variable('beat')),
    procedures.call('step %s %n', 'left', 50),
    procedures.call('spin %n', -360),
)

sprite.when_key_pressed('space')(
    procedures.call('spin %n', 720),
    looks.say('Wheee!'),
    looks.say(''),
)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save', '-o', type=str, help='Save project to .sb3 file')
    args = parser.parse_args()

    from scratch.vm.renderer import Renderer  # noqa: PLC0415

    rt = project.build_runtime()
    if args.save:
        from scratch.sb3.io import save_project

        save_project(rt, args.save)
        print(f'Saved to {args.save}')
    else:
        renderer = Renderer(rt, title=project.name)
        renderer.run()
