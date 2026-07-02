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

from pathlib import Path

from scratch.dsl import Project, data, looks, motion, operators

HERE = Path(__file__).parent

project = Project('Key Mover')

# ── Stage ─────────────────────────────────────────────────────────────
project.stage.var('score', 0)
project.stage.var('moves', 0)

# ── Player sprite ────────────────────────────────────────────────────
player = project.sprite('Player')
player.costume('ball', path=str(HERE / 'ball.svg'))
player.x = 0
player.y = 0

player.var('speed', 3)
player.var('score', 0)

player.when_flag_clicked(
    looks.say('Use arrow keys to move!'),
)

player.when_key_pressed('up arrow')(
    motion.change_y(data.variable('speed')),
    data.change_variable('moves', 1),
)
player.when_key_pressed('down arrow')(
    motion.change_y(operators.sub(0, data.variable('speed'))),
    data.change_variable('moves', 1),
)
player.when_key_pressed('left arrow')(
    motion.change_x(operators.sub(0, data.variable('speed'))),
    data.change_variable('moves', 1),
)
player.when_key_pressed('right arrow')(
    motion.change_x(data.variable('speed')),
    data.change_variable('moves', 1),
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
