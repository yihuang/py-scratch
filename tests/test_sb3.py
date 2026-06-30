"""Round-trip tests: load .sb3 → save → re-load → execute."""

from __future__ import annotations

import io
import json
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any

from scratch.sb3.io import load_assets, load_project, save_project
from scratch.vm.opcodes import OPCODE_MAP
import tempfile
from scratch.sb3.io import _build_project_json

# ── Helpers ──────────────────────────────────────────────────────────────


def _make_1x1_png(r: int, g: int, b: int) -> bytes:
    """Build a minimal valid 1×1 PNG with the given RGB pixel."""
    sig = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
    raw = zlib.compress(bytes([r, g, b]))
    idat_crc = zlib.crc32(b'IDAT' + raw) & 0xFFFFFFFF
    idat = struct.pack('>I', len(raw)) + b'IDAT' + raw + struct.pack('>I', idat_crc)
    iend_crc = zlib.crc32(b'IEND') & 0xFFFFFFFF
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
    return sig + ihdr + idat + iend


def _make_project_json() -> dict[str, Any]:
    """Return a minimal but realistic project.json dict."""
    return {
        'targets': [
            {
                'isStage': True,
                'name': 'Stage',
                'variables': {},
                'lists': {},
                'broadcasts': {},
                'blocks': {},
                'comments': {},
                'costumes': [],
                'sounds': [],
                'currentCostume': 0,
                'volume': 100,
                'layerOrder': 0,
            },
            {
                'isStage': False,
                'name': 'Cat',
                'variables': {'v1': ['score', 0]},
                'lists': {'l1': ['items', ['hello', 'world']]},
                'broadcasts': {},
                'blocks': {
                    'b1': {
                        'opcode': 'event_whenflagclicked',
                        'next': 'b2',
                        'parent': None,
                        'inputs': {},
                        'fields': {},
                        'shadow': False,
                        'topLevel': True,
                        'x': 0,
                        'y': 0,
                    },
                    'b2': {
                        'opcode': 'motion_movesteps',
                        'next': 'b3',
                        'parent': 'b1',
                        'inputs': {'STEPS': [1, 10]},
                        'fields': {},
                        'shadow': False,
                        'topLevel': False,
                    },
                    'b3': {
                        'opcode': 'data_setvariableto',
                        'next': None,
                        'parent': 'b2',
                        'inputs': {'VALUE': [1, 42]},
                        'fields': {'VARIABLE': ['score', 'v1']},
                        'shadow': False,
                        'topLevel': False,
                    },
                },
                'comments': {},
                'costumes': [
                    {
                        'name': 'c1',
                        'dataFormat': 'png',
                        'assetId': 'b',
                        'md5ext': 'b.png',
                        'bitmapResolution': 1,
                        'rotationCenterX': 0.5,
                        'rotationCenterY': 0.5,
                    },
                ],
                'sounds': [],
                'currentCostume': 1,
                'x': 100,
                'y': -50,
                'direction': 45,
                'size': 80,
                'visible': True,
                'volume': 100,
                'layerOrder': 1,
                'rotationStyle': 'all around',
                'draggable': False,
            },
        ],
        'monitors': [],
        'extensions': [],
        'meta': {'semver': '3.0.0', 'vm': '0.2.0', 'agent': 'test'},
    }


def _build_sb3(project: dict[str, Any], png_bytes: bytes) -> io.BytesIO:
    """Write project.json + asset into a BytesIO and return it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('project.json', json.dumps(project, separators=(',', ':')))
        zf.writestr('b.png', png_bytes)
    buf.seek(0)
    return buf


class TestRoundTrip:
    """Round-trip: load → save → re-load → execute."""

    def test_save_and_reload(self) -> None:
        """Save a Runtime to .sb3 and re-load it."""
        project = _make_project_json()
        blue_png = _make_1x1_png(0, 0, 255)
        sb3 = _build_sb3(project, blue_png)

        rt = load_project(sb3)
        sb3.seek(0)
        load_assets(rt, sb3)

        # Save to BytesIO
        out = io.BytesIO()
        save_project(rt, out)
        out.seek(0)

        # Verify zip structure
        with zipfile.ZipFile(out) as zf:
            names = sorted(zf.namelist())
            assert names == ['b.png', 'project.json'], f'got {names}'
            assert zf.read('b.png') == blue_png
            data = json.loads(zf.read('project.json'))
            assert len(data['targets']) == 2

        # Re-load
        out.seek(0)
        rt2 = load_project(out)
        cat = rt2.targets[1]
        assert cat.name == 'Cat'
        assert cat.x == 100
        assert cat.y == -50
        assert cat.direction == 45
        assert cat.size == 80
        assert cat.costume_index == 1

    def test_json_round_trip(self) -> None:
        project = _make_project_json()
        blue_png = _make_1x1_png(0, 0, 255)
        sb3 = _build_sb3(project, blue_png)
        rt = load_project(sb3)
        assert len(rt.targets) == 2

        out = _build_project_json(rt)
        t1 = project['targets'][1]
        t2 = out['targets'][1]
        assert t2['name'] == t1['name']
        assert t2['variables'] == t1['variables']
        assert t2['lists'] == t1['lists']
        assert t2['blocks']['b2']['inputs'] == t1['blocks']['b2']['inputs']
        assert t2['x'] == t1['x']
        assert t2['direction'] == t1['direction']

    def test_variables_and_lists_preserved(self) -> None:
        """Variables and lists survive the round-trip."""
        project = _make_project_json()
        sb3 = _build_sb3(project, _make_1x1_png(0, 0, 255))

        rt = load_project(sb3)
        out = io.BytesIO()
        save_project(rt, out)
        out.seek(0)

        rt2 = load_project(out)
        cat = rt2.targets[1]
        v = cat.lookup_variable('score')
        assert v is not None
        assert v.value == 0
        assert 'l1' in cat.lists
        assert cat.lists['l1'].contents == ['hello', 'world']

    def test_blocks_preserved(self) -> None:
        """Block structure and inputs survive the round-trip."""
        project = _make_project_json()
        sb3 = _build_sb3(project, _make_1x1_png(0, 0, 255))

        rt = load_project(sb3)
        out = io.BytesIO()
        save_project(rt, out)
        out.seek(0)

        rt2 = load_project(out)
        cat = rt2.targets[1]
        assert len(cat.blocks) == 3
        b2 = cat.blocks['b2']
        assert b2.opcode == 'motion_movesteps'
        assert b2.inputs['STEPS'].value == 10
        assert b2.next == 'b3'
        b3 = cat.blocks['b3']
        assert b3.opcode == 'data_setvariableto'
        assert b3.fields['VARIABLE'].value == 'score'
        assert b3.inputs['VALUE'].value == 42

    def test_costume_data_preserved(self) -> None:
        """Costume metadata and raw image bytes survive."""
        project = _make_project_json()
        blue_png = _make_1x1_png(0, 0, 255)
        sb3 = _build_sb3(project, blue_png)

        rt = load_project(sb3)
        sb3.seek(0)
        load_assets(rt, sb3)
        orig = rt.targets[1].costumes[0].data
        assert len(orig) > 0

        out = io.BytesIO()
        save_project(rt, out)
        out.seek(0)

        rt2 = load_project(out)
        assert rt2.targets[1].costumes[0].md5ext == 'b.png'
        assert rt2.targets[1].costumes[0].data_format == 'png'

    def test_reloaded_project_executes(self) -> None:
        """Blocks in a saved-and-reloaded project still run."""
        project = _make_project_json()
        sb3 = _build_sb3(project, _make_1x1_png(0, 0, 255))

        rt = load_project(sb3)
        out = io.BytesIO()
        save_project(rt, out)
        out.seek(0)

        rt2 = load_project(out)
        rt2.register_all(OPCODE_MAP)
        cat = rt2.targets[1]
        cat._rebuild_hat_cache()
        rt2.green_flag()
        for _ in range(10):
            rt2.step()

        v = cat.lookup_variable('score')
        assert v is not None, 'variable not found'
        assert v.value == 42, f'expected 42, got {v.value}'

    def test_asset_bytes_in_saved_file(self) -> None:
        """Saved .sb3 contains correct PNG bytes."""
        project = _make_project_json()
        blue_png = _make_1x1_png(0, 0, 255)
        green_png = _make_1x1_png(0, 255, 0)

        # Add a second costume
        project['targets'][1]['costumes'].append(
            {
                'name': 'c2',
                'dataFormat': 'png',
                'assetId': 'g',
                'md5ext': 'g.png',
                'bitmapResolution': 1,
                'rotationCenterX': 0.5,
                'rotationCenterY': 0.5,
            }
        )

        sb3 = io.BytesIO()
        with zipfile.ZipFile(sb3, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('project.json', json.dumps(project, separators=(',', ':')))
            zf.writestr('b.png', blue_png)
            zf.writestr('g.png', green_png)
        sb3.seek(0)

        rt = load_project(sb3)
        sb3.seek(0)
        load_assets(rt, sb3)

        out = io.BytesIO()
        save_project(rt, out)
        out.seek(0)

        with zipfile.ZipFile(out) as zf:
            assert zf.read('b.png') == blue_png
            assert zf.read('g.png') == green_png

    def test_file_path_round_trip(self) -> None:
        """Save and load via real file path."""

        project = _make_project_json()
        blue_png = _make_1x1_png(0, 0, 255)
        sb3 = _build_sb3(project, blue_png)

        rt = load_project(sb3)
        tmp = Path(tempfile.mkdtemp()) / 'test.sb3'
        save_project(rt, tmp)

        rt2 = load_project(tmp)
        assert rt2.targets[1].name == 'Cat'
        assert rt2.targets[1].x == 100
        tmp.unlink()
