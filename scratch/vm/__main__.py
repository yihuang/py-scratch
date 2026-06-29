#!/usr/bin/env python3
"""
``python3 -m scratch.vm [project.sb3]`` — run a Scratch project.

With no arguments, runs the built-in demo.
With an ``.sb3`` file path, loads, registers opcodes, and runs it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pygame

from scratch.sb3 import load_assets, load_project
from scratch.vm.opcodes import OPCODE_MAP
from scratch.vm.renderer import Renderer


def main() -> None:
    args = sys.argv[1:]

    if args:
        path = Path(args[0])
        if not path.suffix == '.sb3':
            msg = f'Expected .sb3 file, got {path.suffix}'
            sys.exit(msg)

        pygame.display.init()
        pygame.font.init()

        rt = load_project(path)
        load_assets(rt, path)
        rt.register_all(OPCODE_MAP)
        for target in rt.targets:
            target._rebuild_hat_cache()

        renderer = Renderer(rt, title=f'Scratch VM — {path.name}')
        renderer.run()
    else:
        # Fall back to the built-in demo
        from .demo import main as demo_main

        demo_main()


if __name__ == '__main__':
    main()
