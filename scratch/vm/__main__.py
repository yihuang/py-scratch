#!/usr/bin/env python3
"""
``python3 -m scratch.vm [project.sb3]`` — run a Scratch project.

With no arguments, runs a built-in demo.
With an ``.sb3`` file path, loads, registers opcodes, and runs it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pygame

from scratch.sb3 import load_assets, load_project
from scratch.vm import Block, Runtime, Target, make_block
from scratch.vm.opcodes import OPCODE_MAP
from scratch.vm.renderer import Renderer
from scratch.vm.types import Costume, Input


def _circle_costume(name: str, color: tuple[int, ...], r: int = 35) -> Costume:
    surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
    center = (r, r)
    pygame.draw.circle(surf, color, center, r)
    pygame.draw.circle(surf, (0, 0, 0), center, r, 2)
    return Costume(
        name=name,
        data_format="pygame",
        bitmap_resolution=1,
        rotation_center_x=r,
        rotation_center_y=r,
        surface=surf,
    )


def _build_demo() -> Runtime:
    rt = Runtime()
    rt.register_all(OPCODE_MAP)

    stage = Target(name="Stage", is_stage=True)
    stage.costumes = [_circle_costume("default", (200, 220, 255, 255), 240)]
    rt.add_target(stage)

    ball = Target(name="Ball")
    ball.costumes = [_circle_costume("ball", (255, 50, 50))]
    ball.blocks = {
        "hat": make_block("event_whenflagclicked", "hat", top_level=True, next_="forever"),
        "forever": make_block(
            "control_forever",
            "forever",
            parent="hat",
            inputs={"SUBSTACK": Input(value="move")},
        ),
        "move": Block(
            id="move",
            opcode="motion_movesteps",
            parent="forever",
            inputs={"STEPS": Input(value=5)},
            next="bounce",
        ),
        "bounce": Block(id="bounce", opcode="motion_ifonedgebounce", parent="forever", next="wait"),
        "wait": Block(
            id="wait",
            opcode="control_wait",
            parent="forever",
            inputs={"DURATION": Input(value=0.01)},
        ),
    }
    ball._rebuild_hat_cache()
    rt.add_target(ball)
    return rt


def main() -> None:
    args = sys.argv[1:]

    if args:
        path = Path(args[0])
        if not path.suffix == ".sb3":
            msg = f"Expected .sb3 file, got {path.suffix}"
            sys.exit(msg)

        pygame.display.init()
        pygame.font.init()

        rt = load_project(path)
        load_assets(rt, path)
        rt.register_all(OPCODE_MAP)
        for target in rt.targets:
            target._rebuild_hat_cache()

        renderer = Renderer(rt, title=f"Scratch VM — {path.name}")
        renderer.run()
    else:
        pygame.display.init()
        pygame.font.init()
        rt = _build_demo()
        renderer = Renderer(rt, title="Scratch VM — Demo")
        renderer.run()


if __name__ == "__main__":
    main()
