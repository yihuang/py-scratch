"""
Validate all example .sb3 files against the official scratch-vm.

Each test:
1. Generates a project from an example script
2. Saves it as .sb3 to a temp file
3. Validates with scratch-vm (node.js)

Skipped automatically if scratch-vm is not installed.
"""

from __future__ import annotations

import importlib
import io
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
VERIFIER_DIR = HERE / "verifier"
VALIDATE_SCRIPT = VERIFIER_DIR / "validate.mjs"
HAS_SCRATCH_VM = (VERIFIER_DIR / "node_modules" / "scratch-vm").is_dir()

_skip_no_scratch_vm = pytest.mark.skipif(
    not HAS_SCRATCH_VM,
    reason="scratch-vm not installed — run: cd tests/verifier && npm install",
)

EXAMPLES = [
    "bouncing_ball",
    "calculator",
    "cat_chase_mouse",
    "circle_walker",
    "key_mover",
    "mouse_follower",
    "pen_artist",
    "all_in_one",
]


def _generate_sb3(example_name: str) -> bytes:
    """Import an example module and save its project to BytesIO."""
    mod = importlib.import_module(f"examples.{example_name}")
    buf = io.BytesIO()
    mod.project.save(buf)
    return buf.getvalue()


@_skip_no_scratch_vm
@pytest.mark.parametrize("example", EXAMPLES)
def test_example_sb3_valid(example: str, tmp_path: Path) -> None:
    """Generate .sb3 from example and validate with scratch-vm."""
    sb3_data = _generate_sb3(example)
    sb3_path = tmp_path / f"{example}.sb3"
    sb3_path.write_bytes(sb3_data)

    result = subprocess.run(
        ["node", str(VALIDATE_SCRIPT), str(sb3_path)],
        cwd=str(VERIFIER_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )

    output = result.stdout + result.stderr
    print(output)

    if result.returncode != 0:
        pytest.fail(f"sb3 validation failed for {example}.sb3\n{output}")
