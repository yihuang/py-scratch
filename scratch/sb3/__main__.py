#!/usr/bin/env python3
"""
``python3 -m scratch.sb3 transcribe <project.sb3> [output_dir]``

Transcribe an .sb3 project into py-scratch DSL Python code.

Examples::

    python -m scratch.sb3 transcribe project.sb3
    python -m scratch.sb3 transcribe project.sb3 ./my_project
    scratch-sb3-transcribe project.sb3 -o ./my_project
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scratch.sb3.transcriber import transcribe_to_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Transcribe .sb3 → py-scratch DSL Python code',
    )
    sub = parser.add_subparsers(dest='command')
    sub.required = False

    trans = sub.add_parser('transcribe', help='Transcribe an .sb3 file to Python')
    trans.add_argument('sb3', type=str, help='Path to the .sb3 file')
    trans.add_argument(
        'output_dir',
        nargs='?',
        default=None,
        help='Output directory (default: <sb3_name>_src/)',
    )
    trans.add_argument(
        '-o',
        '--output',
        dest='output_flag',
        default=None,
        help='Output directory (alternative syntax)',
    )
    trans.add_argument(
        '-a',
        '--asset-dir',
        default=None,
        help='Asset subdirectory name (default: assets)',
    )

    args = parser.parse_args()

    if args.command is None and len(sys.argv) > 1:
        # Bare `scratch-sb3-transcribe project.sb3` — no subcommand
        sb3_path = Path(sys.argv[1])
        if sb3_path.suffix == '.sb3':
            out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
            _run(sb3_path, out, None)
            return
        parser.print_help()
        sys.exit(1)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    sb3_path = Path(args.sb3)
    out = None
    if args.output_flag:
        out = Path(args.output_flag)
    elif args.output_dir:
        out = Path(args.output_dir)

    _run(sb3_path, out, args.asset_dir)


def _run(sb3_path: Path, output_dir: Path | None, asset_dir_arg: str | None) -> None:
    if not sb3_path.exists():
        print(f'Error: {sb3_path} not found', file=sys.stderr)
        sys.exit(1)
    if sb3_path.suffix != '.sb3':
        print(f'Error: expected .sb3 file, got {sb3_path.suffix}', file=sys.stderr)
        sys.exit(1)

    if output_dir is None:
        output_dir = sb3_path.with_suffix('').with_name(sb3_path.stem + '_src')

    transcribe_to_dir(
        sb3_path,
        output_dir,
        asset_dir_name=asset_dir_arg or 'assets',
    )
    print(f'Done. Output: {output_dir.resolve()}')


if __name__ == '__main__':
    main()
