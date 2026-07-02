# Project Rules

## Lint / Format Before Finishing

After completing a task (before committing, creating a PR, or declaring work done),
run the following commands and fix any issues they report:

```
uv run ruff check
uv run ruff format
uv run mypy --explicit-package-bases scratch/
```

## Use Constants Over Hardcoded Strings

Never use raw string literals for values that have a corresponding constant defined in `scratch/vm/constants.py`. Always import and use the constant instead.

### Example

```python
# ❌ Wrong
if sprite.rotation_style == "don't rotate":

# ✅ Correct
from .constants import ROTATION_DONT_ROTATE
if sprite.rotation_style == ROTATION_DONT_ROTATE:
```

### Checklist

When writing or modifying code that involves any of the following, check `constants.py` first for an existing constant:

- Rotation styles (`ROTATION_ALL_AROUND`, `ROTATION_LEFT_RIGHT`, `ROTATION_DONT_ROTATE`)
- Stage boundaries (`STAGE_LEFT`, `STAGE_RIGHT`, `STAGE_TOP`, `STAGE_BOTTOM`)
- Graphic effect names (members of `GRAPHIC_EFFECTS`)
- Sound effect names (`SOUND_EFFECT_PITCH`, `SOUND_EFFECT_PAN`)
- Volume / tempo / pitch / pan ranges (`VOLUME_MIN`, `VOLUME_MAX`, `TEMPO_MIN`, `TEMPO_MAX`, `PITCH_MIN`, `PITCH_MAX`, `PAN_MIN`, `PAN_MAX`)
- Pen properties (`PEN_SIZE_MIN`)
- Special list index values (`LIST_INDEX_ALL`, `LIST_INDEX_LAST`, `LIST_INDEX_RANDOM`)
- Control stop options (`STOP_ALL`, `STOP_THIS_SCRIPT`, `STOP_OTHER_IN_SPRITE`)
