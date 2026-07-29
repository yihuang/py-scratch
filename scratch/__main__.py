#!/usr/bin/env python3
"""
``scratch`` — unified CLI for py-scratch.

Usage::

    scratch run [project.sb3]          # Run a Scratch project (or built-in demo)
    scratch transcribe <project.sb3>   # Transcribe .sb3 → Python DSL source
    scratch transcribe <project.sb3> -o <output_dir>
    scratch --help
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pygame

from scratch.sb3 import load_assets, load_project
from scratch.sb3.transcriber import transcribe_to_dir
from scratch.vm import Block, Runtime, Target, make_block
from scratch.vm.opcodes import OPCODE_MAP
from scratch.vm.renderer import Renderer
from scratch.vm.types import Costume, Input


def _run_demo() -> None:
    pygame.display.init()
    pygame.font.init()

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

    renderer = Renderer(rt, title="Scratch VM — Demo")
    renderer.run()


def _cmd_run(args: argparse.Namespace) -> None:
    path = args.sb3

    if path:
        if not path.suffix == ".sb3":
            print(f"Error: expected .sb3 file, got {path.suffix}", file=sys.stderr)
            sys.exit(1)

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
        _run_demo()


def _cmd_transcribe(args: argparse.Namespace) -> None:
    sb3_path = args.sb3

    if not sb3_path.exists():
        print(f"Error: {sb3_path} not found", file=sys.stderr)
        sys.exit(1)
    if sb3_path.suffix != ".sb3":
        print(f"Error: expected .sb3 file, got {sb3_path.suffix}", file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir
    if output_dir is None:
        output_dir = sb3_path.with_suffix("").with_name(sb3_path.stem + "_src")

    transcribe_to_dir(
        sb3_path,
        output_dir,
        asset_dir_name=args.asset_dir or "assets",
    )
    print(f"Done. Output: {output_dir.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="scratch",
        description="py-scratch: run and transcribe Scratch 3.0 projects",
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    # ── run ──────────────────────────────────────────────────────────
    run_p = sub.add_parser("run", help="Run a Scratch project (or built-in demo)")
    run_p.add_argument(
        "sb3",
        nargs="?",
        type=Path,
        default=None,
        help="Path to the .sb3 project file (default: built-in demo)",
    )
    run_p.set_defaults(func=_cmd_run)

    # ── transcribe ───────────────────────────────────────────────────
    trans_p = sub.add_parser("transcribe", help="Transcribe .sb3 → Python DSL source")
    trans_p.add_argument("sb3", type=Path, help="Path to the .sb3 file")
    trans_p.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        default=None,
        help="Output directory (default: <sb3_stem>_src/)",
    )
    trans_p.add_argument(
        "-o",
        "--output",
        dest="output_dir",
        type=Path,
        default=None,
        help="Output directory (alternative syntax)",
    )
    trans_p.add_argument(
        "-a",
        "--asset-dir",
        default=None,
        help="Asset subdirectory name (default: assets)",
    )
    trans_p.set_defaults(func=_cmd_transcribe)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
