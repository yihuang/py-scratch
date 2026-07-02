"""
Shared constants for the Scratch VM.

Mirrors the official Scratch 3.0 runtime conventions.
"""

from __future__ import annotations

import enum

# ═════════════════════════════════════════════════════════════════════════
#  Stage dimensions
# ═════════════════════════════════════════════════════════════════════════

STAGE_W: int = 480
STAGE_H: int = 360

STAGE_LEFT: float = -STAGE_W / 2  # -240
STAGE_RIGHT: float = STAGE_W / 2  #  240
STAGE_TOP: float = STAGE_H / 2  #  180
STAGE_BOTTOM: float = -STAGE_H / 2  # -180

# ═════════════════════════════════════════════════════════════════════════
#  Motion / direction
# ═════════════════════════════════════════════════════════════════════════

# Scratch direction convention: 0 = up, 90 = right (default)
SCRATCH_RIGHT: float = 90.0
SCRATCH_UP: float = 0.0

# When bouncing off an edge, direction is reflected
BOUNCE_REFLECT_ANGLE: float = 180.0

# ═════════════════════════════════════════════════════════════════════════
#  Rotation styles
# ═════════════════════════════════════════════════════════════════════════

ROTATION_ALL_AROUND: str = 'all around'
ROTATION_LEFT_RIGHT: str = 'left-right'
ROTATION_DONT_ROTATE: str = "don't rotate"

# ═════════════════════════════════════════════════════════════════════════
#  Default target values
# ═════════════════════════════════════════════════════════════════════════

DEFAULT_DIRECTION: float = SCRATCH_RIGHT
DEFAULT_SIZE_PCT: float = 100.0  # percent
DEFAULT_VOLUME_PCT: float = 100.0
DEFAULT_TEMPO_BPM: float = 60.0
DEFAULT_LAYER_ORDER: int = 0
DEFAULT_PEN_SIZE: float = 1.0
DEFAULT_PEN_SATURATION: float = 100.0
DEFAULT_PEN_BRIGHTNESS: float = 100.0
DEFAULT_PEN_COLOR: tuple[int, int, int] = (0, 0, 255)

# ═════════════════════════════════════════════════════════════════════════
#  Sound effect names & bounds
# ═════════════════════════════════════════════════════════════════════════

SOUND_EFFECT_PITCH: str = 'PITCH'
SOUND_EFFECT_PAN: str = 'PAN'

PITCH_MIN: float = -360.0
PITCH_MAX: float = 360.0
PAN_MIN: float = -100.0
PAN_MAX: float = 100.0

# ═════════════════════════════════════════════════════════════════════════
#  Graphic effect names
# ═════════════════════════════════════════════════════════════════════════

GRAPHIC_EFFECTS: tuple[str, ...] = (
    'color',
    'fisheye',
    'whirl',
    'pixelate',
    'mosaic',
    'brightness',
    'ghost',
)

# ═════════════════════════════════════════════════════════════════════════
#  Volume bounds

VOLUME_MIN: float = 0.0
VOLUME_MAX: float = 100.0

# ═════════════════════════════════════════════════════════════════════════
#  Tempo bounds
# ═════════════════════════════════════════════════════════════════════════

TEMPO_MIN: float = 20.0
TEMPO_MAX: float = 500.0

# ═════════════════════════════════════════════════════════════════════════
#  Pen
# ═════════════════════════════════════════════════════════════════════════

PEN_SIZE_MIN: float = 0.0

# ═════════════════════════════════════════════════════════════════════════
#  Look effects / bubble display
# ═════════════════════════════════════════════════════════════════════════

LOOKS_NEXTCOSTUME_OFFSET: int = 2  # +2 because _set_costume is 1-based

BUBBLE_MAX_CHARS: int = 330

BUBBLE_DECIMAL_THRESHOLD: float = 0.01

# ═════════════════════════════════════════════════════════════════════════
#  List special index values
# ═════════════════════════════════════════════════════════════════════════

LIST_INDEX_ALL: str = 'all'
LIST_INDEX_LAST: str = 'last'
LIST_INDEX_RANDOM: str = 'random'
LIST_INDEX_ANY: str = 'any'
LIST_INDEX_ALL_SENTINEL: str = 'ALL'  # internal sentinel

# ═════════════════════════════════════════════════════════════════════════
#  Control stop options
# ═════════════════════════════════════════════════════════════════════════

STOP_ALL: str = 'all'
STOP_THIS_SCRIPT: str = 'this script'
STOP_OTHER_IN_SPRITE: str = 'other scripts in sprite'
STOP_OTHER_IN_STAGE: str = 'other scripts in stage'

# ═════════════════════════════════════════════════════════════════════════
#  Math / operators
# ═════════════════════════════════════════════════════════════════════════

MATH_TRIG_PRECISION: int = 10  # rounding for sin/cos results

# ═════════════════════════════════════════════════════════════════════════
#  Time / sensing
# ═════════════════════════════════════════════════════════════════════════

SECONDS_PER_DAY: float = 86400.0
DST_OFFSET_SECS: int = 3600
YEAR_2000_EPOCH: tuple[int, int, int, int, int, int, int, int, int] = (2000, 1, 1, 0, 0, 0, 0, 0, 0)

# ═════════════════════════════════════════════════════════════════════════
#  Distance default
# ═════════════════════════════════════════════════════════════════════════

DISTANCE_UNREACHABLE: float = 10000.0

# ═════════════════════════════════════════════════════════════════════════
#  Collision / click hit-test
# ═════════════════════════════════════════════════════════════════════════

CLICK_HIT_RADIUS: float = 30.0


# ═════════════════════════════════════════════════════════════════════════
#  Scratch JSON primitive type codes
# ═════════════════════════════════════════════════════════════════════════


class PrimitiveType(enum.IntEnum):
    """Scratch 3.0 inlined primitive type codes.

    The type code is the first element of ``[type_code, value, ...]`` arrays
    embedded directly in block input data (as opposed to block-id references).
    """

    NUMBER = 4
    POSITIVE_NUMBER = 5
    WHOLE_NUMBER = 6
    INTEGER = 7
    ANGLE = 8
    COLOR_PICKER = 9
    TEXT = 10
    BROADCAST = 11
    VARIABLE = 12
    LIST = 13


# ═════════════════════════════════════════════════════════════════════════
#  Scratch JSON shadow / block-reference flags
# ═════════════════════════════════════════════════════════════════════════

SHADOW_FLAG: int = 1  # [1, literal] — shadow with literal value
BLOCK_REF_FLAG: int = 2  # [2, block_id] — reference to another block
OBSOLETE_FLAG: int = 3  # [3, value, block_id] — obsolete shadow + block

# ═════════════════════════════════════════════════════════════════════════
#  Serialization defaults
# ═════════════════════════════════════════════════════════════════════════

SERIALIZE_TEMPO: float = 60.0
SERIALIZE_VIDEO_TRANSPARENCY: int = 50
SERIALIZE_VIDEO_STATE: str = 'on'

# ═════════════════════════════════════════════════════════════════════════
#  Version metadata
# ═════════════════════════════════════════════════════════════════════════

PROJECT_SEMVER: str = '3.0.0'
VM_VERSION: str = '0.2.0'
VM_AGENT: str = 'py-scratch'

# ═════════════════════════════════════════════════════════════════════════
#  Hat opcodes used internally by the runtime
# ═════════════════════════════════════════════════════════════════════════

CLONE_START_HATS: tuple[str, ...] = ('control_start_as_clone',)
