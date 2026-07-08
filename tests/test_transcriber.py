"""Tests for the SB3-to-DSL transcriber module."""

from __future__ import annotations

import json
import io
import struct
import zipfile
import zlib
import tempfile
from pathlib import Path


from scratch.sb3.transcriber import (
    _safe_name,
    _format_literal,
    _resolve_variable_name,
    _decompile_chain,
    _decompile_block,
    transcribe_to_dir,
    _build_input_args,
    _emit_variables,
    _emit_lists,
    _INPUT_PARAM_MAP,
    _FIELD_PARAM_MAP,
    _FIELD_POSITIONAL_ARGS,
)
from scratch.vm.target import Target, Variable, ListVar
from scratch.vm.types import Block, Input, Field, Mutation


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_1x1_png(r: int = 128, g: int = 128, b: int = 128) -> bytes:
    """Build a minimal valid 1x1 PNG."""
    sig = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    raw = zlib.compress(bytes([r, g, b]))
    idat_crc = zlib.crc32(b"IDAT" + raw) & 0xFFFFFFFF
    idat = struct.pack(">I", len(raw)) + b"IDAT" + raw + struct.pack(">I", idat_crc)
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return sig + ihdr + idat + iend


def _op(
    opcode: str,
    *,
    next_id: str | None = None,
    parent: str | None = None,
    inputs: dict[str, Input] | None = None,
    fields: dict[str, Field] | None = None,
    top_level: bool = False,
    bid: str | None = None,
) -> Block:
    return Block(
        id=bid or opcode,
        opcode=opcode,
        next=next_id,
        parent=parent,
        inputs=inputs or {},
        fields=fields or {},
        shadow=False,
        top_level=top_level,
    )


def _make_tgt(name: str = "Sprite", is_stage: bool = False) -> Target:
    """Create a minimal target."""
    tgt = Target(name=name, is_stage=is_stage)
    if is_stage:
        tgt.variables["v1"] = Variable("score", 0)
    return tgt


def _inp(value: int | float | str, shadow: bool = True) -> Input:
    """Create a literal input."""
    return Input(value=value, shadow=shadow, is_literal=shadow)


def _inp_block(bid: str) -> Input:
    """Create a block-reference input."""
    return Input(value=bid, shadow=False, is_literal=False)


def _field(value: str, id_: str | None = None) -> Field:
    return Field(value=value, id=id_)


# ── Tests: _safe_name ────────────────────────────────────────────────────


class TestSafeName:
    def test_basic(self) -> None:
        assert _safe_name("Cat") == "Cat"

    def test_with_spaces(self) -> None:
        assert _safe_name("My Sprite") == "My_Sprite"

    def test_with_special_chars(self) -> None:
        assert _safe_name("Sprite#1!") == "Sprite_1_"

    def test_reserved_keyword(self) -> None:
        assert _safe_name("if") == "if_"

    def test_starts_with_digit(self) -> None:
        assert _safe_name("123abc") == "_123abc"

    def test_empty(self) -> None:
        assert _safe_name("") == "_"


# ── Tests: _format_literal ───────────────────────────────────────────────


class TestFormatLiteral:
    def test_int(self) -> None:
        assert _format_literal(42) == "42"

    def test_float_whole(self) -> None:
        assert _format_literal(10.0) == "10"

    def test_float_fraction(self) -> None:
        assert _format_literal(3.14) == "3.14"

    def test_string(self) -> None:
        assert _format_literal("hello") == "'hello'"

    def test_string_with_quote(self) -> None:
        assert _format_literal("it's") == r"'it\'s'"

    def test_bool(self) -> None:
        assert _format_literal(True) == "True"
        assert _format_literal(False) == "False"

    def test_none(self) -> None:
        assert _format_literal(None) == "0"


# ── Tests: _resolve_variable_name ────────────────────────────────────────


class TestResolveVariable:
    def test_by_id(self) -> None:
        tgt = _make_tgt(is_stage=True)
        block = _op("data_variable", fields={"VARIABLE": _field("score", "v1")})
        assert _resolve_variable_name(tgt, block) == "score"

    def test_by_value_fallback(self) -> None:
        tgt = _make_tgt()
        block = _op("data_variable", fields={"VARIABLE": _field("count", None)})
        assert _resolve_variable_name(tgt, block) == "count"


# ── Tests: _decompile_block ──────────────────────────────────────────────


class TestDecompileBlock:
    """Test decompilation of individual blocks."""

    def test_motion_move(self) -> None:
        tgt = _make_tgt()
        block = _op("motion_movesteps", inputs={"STEPS": _inp(10)})
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        assert expr["opcode"] == "motion_movesteps"
        assert expr["mod"] == "motion"
        assert expr["func"] == "move"
        assert expr["args"][0]["value"] == "10"
        assert expr["body"] is None

    def test_data_set_variable(self) -> None:
        tgt = _make_tgt(is_stage=True)
        block = _op(
            "data_setvariableto",
            inputs={"VALUE": _inp(42)},
            fields={"VARIABLE": _field("score", "v1")},
        )
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        assert expr["opcode"] == "data_setvariableto"
        assert expr["mod"] == "data"
        assert expr["func"] == "set_variable"

    def test_data_variable_reporter(self) -> None:
        tgt = _make_tgt(is_stage=True)
        block = _op("data_variable", fields={"VARIABLE": _field("score", "v1")})
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "reporter"
        assert "data.variable('score')" in expr["code"]

    def test_control_wait(self) -> None:
        tgt = _make_tgt()
        block = _op("control_wait", inputs={"DURATION": _inp(1.0)})
        expr = _decompile_block(tgt, block)
        assert expr["mod"] == "control"
        assert expr["func"] == "wait"

    def test_operator_add(self) -> None:
        tgt = _make_tgt(is_stage=True)
        block = _op(
            "operator_add",
            inputs={"NUM1": _inp(5), "NUM2": _inp(3)},
        )
        expr = _decompile_block(tgt, block)
        assert expr["mod"] == "operators"
        assert expr["func"] == "add"

    def test_unknown_opcode(self) -> None:
        tgt = _make_tgt()
        block = _op("some_fake_opcode")
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "comment"

    def test_control_repeat(self) -> None:
        tgt = _make_tgt()
        sub_id = "sub1"
        sub = _op("motion_movesteps", inputs={"STEPS": _inp(5)}, bid=sub_id)
        tgt.blocks[sub_id] = sub
        block = _op(
            "control_repeat",
            inputs={"TIMES": _inp(10), "SUBSTACK": _inp_block(sub_id)},
        )
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        assert expr["func"] == "repeat"
        assert expr["body"] is not None
        assert len(expr["body"]) == 1
        assert expr["body"][0]["opcode"] == "motion_movesteps"

    def test_control_if_else(self) -> None:
        tgt = _make_tgt(is_stage=True)
        tgt.blocks["then1"] = _op("motion_movesteps", inputs={"STEPS": _inp(10)}, bid="then1")
        tgt.blocks["else1"] = _op("motion_turnright", inputs={"DEGREES": _inp(15)}, bid="else1")
        cond_block = _op(
            "operator_gt", inputs={"OPERAND1": _inp(5), "OPERAND2": _inp(3)}, bid="cond1"
        )
        tgt.blocks["cond1"] = cond_block

        block = _op(
            "control_if_else",
            inputs={
                "CONDITION": _inp_block("cond1"),
                "SUBSTACK": _inp_block("then1"),
                "SUBSTACK2": _inp_block("else1"),
            },
        )
        expr = _decompile_block(tgt, block)
        assert expr["func"] == "if_else"
        assert expr["body"] is not None
        assert len(expr["body"]) == 1
        assert expr["body2"] is not None
        assert len(expr["body2"]) == 1

    def test_operator_mathop_sqrt(self) -> None:
        tgt = _make_tgt()
        block = _op(
            "operator_mathop",
            inputs={"NUM": _inp(25)},
            fields={"OPERATOR": _field("sqrt", None)},
        )
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "reporter"
        assert expr["func"] == "sqrt"
        assert expr["mod"] == "operators"


# ── Tests: _decompile_chain ──────────────────────────────────────────────


class TestDecompileChain:
    def test_empty_chain(self) -> None:
        tgt = _make_tgt()
        assert _decompile_chain(tgt, None) == []

    def test_single_block(self) -> None:
        tgt = _make_tgt()
        tgt.blocks["b1"] = _op("motion_movesteps", inputs={"STEPS": _inp(10)}, bid="b1")
        exprs = _decompile_chain(tgt, "b1")
        assert len(exprs) == 1
        assert exprs[0]["opcode"] == "motion_movesteps"

    def test_multi_block_chain(self) -> None:
        tgt = _make_tgt()
        tgt.blocks["b1"] = _op(
            "motion_movesteps", inputs={"STEPS": _inp(10)}, next_id="b2", bid="b1"
        )
        tgt.blocks["b2"] = _op(
            "motion_turnright", inputs={"DEGREES": _inp(15)}, next_id=None, bid="b2"
        )
        exprs = _decompile_chain(tgt, "b1")
        assert len(exprs) == 2
        assert exprs[0]["opcode"] == "motion_movesteps"
        assert exprs[1]["opcode"] == "motion_turnright"


# ── Tests: Integration - transcribe with a real .sb3 ─────────────────────


def _build_test_sb3() -> io.BytesIO:
    """Build a BytesIO containing a valid multi-target .sb3 with a stage and sprite."""
    project = {
        "targets": [
            {
                "isStage": True,
                "name": "Stage",
                "variables": {"sv1": ["score", 0]},
                "lists": {"sl1": ["highscores", [100, 200]]},
                "broadcasts": {},
                "blocks": {
                    "sb1": {
                        "opcode": "event_whenflagclicked",
                        "next": "sb2",
                        "parent": None,
                        "inputs": {},
                        "fields": {},
                        "shadow": False,
                        "topLevel": True,
                        "x": 0,
                        "y": 0,
                    },
                    "sb2": {
                        "opcode": "data_setvariableto",
                        "next": None,
                        "parent": "sb1",
                        "inputs": {"VALUE": [1, [4, 10]]},
                        "fields": {"VARIABLE": ["score", "sv1"]},
                        "shadow": False,
                        "topLevel": False,
                    },
                },
                "comments": {},
                "costumes": [],
                "sounds": [],
                "currentCostume": 0,
                "volume": 100,
                "layerOrder": 0,
            },
            {
                "isStage": False,
                "name": "Cat",
                "variables": {"v1": ["speed", 5]},
                "lists": {},
                "broadcasts": {},
                "blocks": {
                    "h1": {
                        "opcode": "event_whenflagclicked",
                        "next": "h2",
                        "parent": None,
                        "inputs": {},
                        "fields": {},
                        "shadow": False,
                        "topLevel": True,
                        "x": 0,
                        "y": 0,
                    },
                    "h2": {
                        "opcode": "control_forever",
                        "next": None,
                        "parent": "h1",
                        "inputs": {"SUBSTACK": [2, "h3"]},
                        "fields": {},
                        "shadow": False,
                        "topLevel": False,
                    },
                    "h3": {
                        "opcode": "motion_movesteps",
                        "next": "h4",
                        "parent": "h2",
                        "inputs": {"STEPS": [1, [4, 10]]},
                        "fields": {},
                        "shadow": False,
                        "topLevel": False,
                    },
                    "h4": {
                        "opcode": "motion_ifonedgebounce",
                        "next": None,
                        "parent": "h3",
                        "inputs": {},
                        "fields": {},
                        "shadow": False,
                        "topLevel": False,
                    },
                },
                "comments": {},
                "costumes": [
                    {
                        "name": "cat-a",
                        "dataFormat": "png",
                        "assetId": "a",
                        "md5ext": "a.png",
                        "bitmapResolution": 1,
                        "rotationCenterX": 0,
                        "rotationCenterY": 0,
                    },
                ],
                "sounds": [],
                "currentCostume": 0,
                "x": 0,
                "y": 0,
                "direction": 90,
                "size": 100,
                "visible": True,
                "volume": 100,
                "layerOrder": 1,
                "rotationStyle": "all around",
                "draggable": False,
            },
        ],
        "monitors": [],
        "extensions": [],
        "meta": {"semver": "3.0.0", "vm": "0.2.0", "agent": "test"},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(project, separators=(",", ":")))
        zf.writestr("a.png", _make_1x1_png(255, 0, 0))
    buf.seek(0)
    return buf


class TestTranscribeIntegration:
    """Integration tests: transcribe a full .sb3 file."""

    def test_transcribe_to_dir(self) -> None:
        """Transcribe a two-target .sb3 and verify output structure."""
        sb3_data = _build_test_sb3()

        with tempfile.TemporaryDirectory() as tmpdir:
            sb3_path = Path(tmpdir) / "test.sb3"
            sb3_path.write_bytes(sb3_data.getvalue())

            out_dir = Path(tmpdir) / "game_src"
            transcribe_to_dir(sb3_path, out_dir)

            # single .py file + assets inside the dir
            assert (out_dir / "main.py").exists()
            # Asset files are extracted using their zip-entry name (md5ext).
            # In the test sb3, the costume's md5ext is 'a.png'.
            assert (out_dir / "assets" / "a.png").exists()

    def test_transcribed_code_has_expected_content(self) -> None:
        """Verify the generated Python code contains expected DSL patterns."""
        sb3_data = _build_test_sb3()

        with tempfile.TemporaryDirectory() as tmpdir:
            sb3_path = Path(tmpdir) / "test.sb3"
            sb3_path.write_bytes(sb3_data.getvalue())

            out_dir = Path(tmpdir) / "game_src"
            transcribe_to_dir(sb3_path, out_dir)

            code = (out_dir / "main.py").read_text()

            # Top-level project variable with everything wired
            assert "project.sprite('Cat')" in code
            assert "stage.var" in code

            # Sprite: has motion blocks, control_forever
            assert "control.forever" in code
            assert "motion.move" in code
            assert "motion.if_on_edge_bounce" in code
            assert "costume" in code

            # No build_project wrapper — code is at top level
            assert "build_project" not in code

    def test_transcribed_code_executable(self) -> None:
        """Verify the generated Python code is syntactically valid."""
        sb3_data = _build_test_sb3()

        with tempfile.TemporaryDirectory() as tmpdir:
            sb3_path = Path(tmpdir) / "test.sb3"
            sb3_path.write_bytes(sb3_data.getvalue())

            out_dir = Path(tmpdir) / "game_src"
            transcribe_to_dir(sb3_path, out_dir)

            code = (out_dir / "main.py").read_text()
            compile(code, "main.py", "exec")

    def test_transcribe_stage_only(self) -> None:
        """Stage-only project."""
        project = {
            "targets": [
                {
                    "isStage": True,
                    "name": "Stage",
                    "variables": {},
                    "lists": {},
                    "broadcasts": {},
                    "blocks": {
                        "b1": {
                            "opcode": "event_whenflagclicked",
                            "next": None,
                            "parent": None,
                            "inputs": {},
                            "fields": {},
                            "shadow": False,
                            "topLevel": True,
                            "x": 0,
                            "y": 0,
                        },
                    },
                    "comments": {},
                    "costumes": [],
                    "sounds": [],
                    "currentCostume": 0,
                    "volume": 100,
                    "layerOrder": 0,
                },
            ],
            "monitors": [],
            "extensions": [],
            "meta": {"semver": "3.0.0", "vm": "0.2.0", "agent": "test"},
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.json", json.dumps(project, separators=(",", ":")))
        buf.seek(0)

        with tempfile.TemporaryDirectory() as tmpdir:
            sb3_path = Path(tmpdir) / "test.sb3"
            sb3_path.write_bytes(buf.getvalue())

            out_dir = Path(tmpdir) / "game_src"
            transcribe_to_dir(sb3_path, out_dir)

            code = (out_dir / "main.py").read_text()
            compile(code, "main.py", "exec")


# ═════════════════════════════════════════════════════════════════════════
#  Decompile — additional blocks
# ═════════════════════════════════════════════════════════════════════════


class TestDecompileBlockExtended:
    """Decompile blocks that were previously uncovered."""

    def test_procedures_call_no_args(self) -> None:
        """procedures_call with no arguments."""
        mut = Mutation(
            proccode="my_block", argumentids="[]", argumentnames="[]", argumentdefaults="[]"
        )
        bid = "call1"
        block = Block(id=bid, opcode="procedures_call", inputs={}, fields={}, mutation=mut)
        tgt = _make_tgt()
        tgt.blocks[bid] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        assert expr["func"] == "call"
        assert expr["mod"] == "procedures"
        assert "'my_block'" in str(expr["args"][0])

    def test_procedures_call_with_args(self) -> None:
        """procedures_call with one argument."""
        arg_id = "arg1"
        mut = Mutation(
            proccode="delete %s",
            argumentids=json.dumps([arg_id]),
            argumentnames=json.dumps(["item"]),
            argumentdefaults=json.dumps([""]),
        )
        bid = "call1"
        block = Block(
            id=bid,
            opcode="procedures_call",
            inputs={arg_id: _inp("hello")},
            fields={},
            mutation=mut,
        )
        tgt = _make_tgt()
        tgt.blocks[bid] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        assert len(expr["args"]) >= 1
        assert "'delete %s'" in str(expr["args"][0])

    def test_procedures_call_no_mutation(self) -> None:
        """procedures_call without mutation → comment placeholder."""
        block = _op("procedures_call", bid="call1")
        tgt = _make_tgt()
        tgt.blocks["call1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "comment"

    def test_argument_reporter_string_number(self) -> None:
        """argument_reporter_string_number → procedures.arg()."""
        block = _op(
            "argument_reporter_string_number",
            bid="arg1",
            fields={"VALUE": Field(value="param1")},
        )
        tgt = _make_tgt()
        tgt.blocks["arg1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "reporter"
        assert "procedures.arg" in expr["code"]
        assert "param1" in expr["code"]

    def test_argument_reporter_boolean(self) -> None:
        """argument_reporter_boolean → procedures.arg()."""
        block = _op(
            "argument_reporter_boolean",
            bid="arg1",
            fields={"VALUE": Field(value="cond")},
        )
        tgt = _make_tgt()
        tgt.blocks["arg1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "reporter"
        assert "procedures.arg" in expr["code"]

    def test_operator_not_with_operand(self) -> None:
        """operator_not with OPERAND input."""
        block = _op(
            "operator_not",
            bid="not1",
            inputs={"OPERAND": _inp(1)},
        )
        tgt = _make_tgt()
        tgt.blocks["not1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        assert len(expr["args"]) == 1
        assert "1" in str(expr["args"][0]) or "1" in str(expr["args"])

    def test_operator_not_no_inputs(self) -> None:
        """operator_not with no inputs → defaults to 0."""
        block = _op("operator_not", bid="not1", inputs={})
        tgt = _make_tgt()
        tgt.blocks["not1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        # Should have default '0' for missing OPERAND
        args_str = str(expr["args"])
        assert "0" in args_str

    def test_control_if_with_condition(self) -> None:
        """control_if with CONDITION input."""
        block = _op(
            "control_if",
            bid="if1",
            inputs={"CONDITION": _inp(1)},
        )
        tgt = _make_tgt()
        tgt.blocks["if1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        assert expr["opcode"] == "control_if"

    def test_control_if_no_condition(self) -> None:
        """control_if with no CONDITION input → defaults to 0."""
        block = _op(
            "control_if",
            bid="if1",
            inputs={"SUBSTACK": _inp("body1")},
        )
        tgt = _make_tgt()
        tgt.blocks["if1"] = block
        tgt.blocks["body1"] = _op("motion_movesteps", bid="body1")
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        # Should have default '0' for missing CONDITION after _INPUT_PARAM_MAP fix
        args_str = str(expr["args"])
        assert "0" in args_str

    def test_control_if_else(self) -> None:
        """control_if_else with both branches."""
        block = _op(
            "control_if_else",
            bid="ife1",
            inputs={"CONDITION": _inp(1)},
        )
        tgt = _make_tgt()
        tgt.blocks["ife1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        assert expr["opcode"] == "control_if_else"

    def test_sensing_keypressed(self) -> None:
        """sensing_keypressed field mapped to 'key' not 'key_option'."""
        block = _op(
            "sensing_keypressed",
            bid="key1",
            fields={"KEY_OPTION": Field(value="right arrow")},
        )
        tgt = _make_tgt()
        tgt.blocks["key1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        # The keyword arg should be 'key=' not 'key_option='
        kwargs_str = str(expr["kwargs"])
        assert "'key'" in kwargs_str or "key=" in kwargs_str
        # 'key_option' should not appear
        assert "key_option" not in kwargs_str

    def test_operator_mathop_ceiling(self) -> None:
        """operator_mathop with 'ceiling' — not in special list → _mathop."""
        block = _op(
            "operator_mathop",
            bid="m1",
            inputs={"NUM": _inp(3.5)},
            fields={"OPERATOR": Field(value="ceiling")},
        )
        tgt = _make_tgt()
        tgt.blocks["m1"] = block
        expr = _decompile_block(tgt, block)
        # 'ceiling' is NOT in the special handler list
        # Falls through to general handler → _mathop with 'ceiling' as positional
        assert expr["func"] == "_mathop"
        args_str = str(expr.get("args", []))
        assert "'ceiling'" in args_str

    def test_operator_mathop_unknown(self) -> None:
        """operator_mathop with unknown operator → _mathop('op', n) positional."""
        block = _op(
            "operator_mathop",
            bid="m1",
            inputs={"NUM": _inp(42)},
            fields={"OPERATOR": Field(value="e ^")},
        )
        tgt = _make_tgt()
        tgt.blocks["m1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        assert expr["func"] == "_mathop"
        # Should have operator name as first positional arg
        args = expr.get("args", [])
        assert len(args) >= 1

    def test_looks_costume_number_name(self) -> None:
        """looks_costumenumbername returns call with number_name kwarg."""
        block = _op(
            "looks_costumenumbername",
            bid="c1",
            fields={"NUMBER_NAME": Field(value="name")},
        )
        tgt = _make_tgt()
        tgt.blocks["c1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["func"] == "costume_number_name"
        assert "number_name" in str(expr.get("kwargs", {}))

    def test_pen_set_pen_color_param(self) -> None:
        """pen_setPenColorParamTo skips VALUE input."""
        block = _op(
            "pen_setPenColorParamTo",
            bid="p1",
            inputs={
                "COLOR_PARAM": _inp("color"),
                "VALUE": _inp(50),
            },
        )
        tgt = _make_tgt()
        tgt.blocks["p1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "call"
        # VALUE should be excluded; only COLOR_PARAM remains
        arg_names = [a.get("name", "") if isinstance(a, dict) else "" for a in expr.get("args", [])]
        assert "color" in arg_names
        assert "value" not in arg_names

    def test_data_variable_reporter_field(self) -> None:
        """data_variable reporter resolves name."""
        block = _op(
            "data_variable",
            bid="v1",
            fields={"VARIABLE": Field(value="score", variable_type="", id="v1")},
        )
        tgt = _make_tgt()
        tgt.variables["v1"] = Variable("score", 0)
        tgt.blocks["v1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "reporter"
        assert "score" in expr["code"]

    def test_unknown_opcode_fallback(self) -> None:
        """Unknown opcode → comment."""
        block = _op("some_unknown_opcode", bid="u1")
        tgt = _make_tgt()
        tgt.blocks["u1"] = block
        expr = _decompile_block(tgt, block)
        assert expr["kind"] == "comment"


# ═════════════════════════════════════════════════════════════════════════
#  Emit — variables and lists deduplication
# ═════════════════════════════════════════════════════════════════════════


class TestEmitDeduplicate:
    """_emit_variables and _emit_lists deduplicate by name."""

    def test_deduplicate_variables(self) -> None:
        """Same variable name emitted only once."""
        tgt = _make_tgt()
        tgt.variables["a"] = Variable("x", 1)
        tgt.variables["b"] = Variable("x", 2)  # same name, different ID
        lines: list[str] = []
        _emit_variables(lines, "", tgt, "sprite")
        var_lines = [line for line in lines if ".var(" in line]
        assert len(var_lines) == 1  # only one declaration

    def test_deduplicate_variables_takes_first(self) -> None:
        """When deduplicating, the first occurrence's value is used."""
        tgt = _make_tgt()
        tgt.variables["a"] = Variable("score", 0)
        tgt.variables["b"] = Variable("score", 100)  # duplicate name
        lines: list[str] = []
        _emit_variables(lines, "", tgt, "sprite")
        var_lines = [line for line in lines if ".var(" in line]
        assert len(var_lines) == 1
        assert "0" in var_lines[0]  # uses first value

    def test_deduplicate_lists(self) -> None:
        """Same list name emitted only once."""

        tgt = _make_tgt()
        tgt.lists["a"] = ListVar("items", [1, 2])
        tgt.lists["b"] = ListVar("items", [3, 4])  # same name
        lines: list[str] = []
        _emit_lists(lines, "", tgt, "sprite")
        list_lines = [line for line in lines if ".list_" in line]
        assert len(list_lines) == 1

    def test_different_names_not_deduplicated(self) -> None:
        """Different variable names are both emitted."""
        tgt = _make_tgt()
        tgt.variables["a"] = Variable("x", 1)
        tgt.variables["b"] = Variable("y", 2)
        lines: list[str] = []
        _emit_variables(lines, "", tgt, "sprite")
        var_lines = [line for line in lines if ".var(" in line]
        assert len(var_lines) == 2


# ═════════════════════════════════════════════════════════════════════════
#  Build input args — edge cases
# ═════════════════════════════════════════════════════════════════════════


class TestBuildInputArgs:
    """_build_input_args edge cases."""

    def test_missing_input_default(self) -> None:
        """Missing required input gets default 0."""
        block = _op("operator_not", bid="n1", inputs={})
        tgt = _make_tgt()
        args = _build_input_args(tgt, block)
        # Should supply default '0' for missing OPERAND
        assert len(args) == 1
        assert args[0]["value"] == "0"  # type: ignore[index]

    def test_missing_input_control_if(self) -> None:
        """control_if with missing CONDITION gets default."""
        block = _op("control_if", bid="if1", inputs={"SUBSTACK": _inp("b1")})
        tgt = _make_tgt()
        args = _build_input_args(tgt, block)
        # After _INPUT_PARAM_MAP fix, should supply default
        assert len(args) >= 1

    def test_pen_value_skipped(self) -> None:
        """pen_setPenColorParamTo skips VALUE input."""
        block = _op(
            "pen_setPenColorParamTo",
            bid="p1",
            inputs={"COLOR_PARAM": _inp("color"), "VALUE": _inp(50)},
        )
        tgt = _make_tgt()
        args = _build_input_args(tgt, block)
        arg_names = [a["name"] for a in args]  # type: ignore[index]
        assert "color" in arg_names
        assert "value" not in arg_names  # VALUE should be skipped

    def test_pen_change_skipped(self) -> None:
        """pen_changePenColorParamBy skips VALUE input."""
        block = _op(
            "pen_changePenColorParamBy",
            bid="p1",
            inputs={"COLOR_PARAM": _inp("color"), "VALUE": _inp(10)},
        )
        tgt = _make_tgt()
        args = _build_input_args(tgt, block)
        arg_names = [a["name"] for a in args]  # type: ignore[index]
        assert "change" in arg_names
        assert "value" not in arg_names

    def test_input_param_map_has_control_if(self) -> None:
        """control_if is in _INPUT_PARAM_MAP."""
        assert "control_if" in _INPUT_PARAM_MAP
        assert _INPUT_PARAM_MAP["control_if"]["CONDITION"] == "condition"

    def test_field_param_map_has_sensing_keypressed(self) -> None:
        """sensing_keypressed is in _FIELD_PARAM_MAP (not _INPUT_PARAM_MAP)."""
        assert "sensing_keypressed" in _FIELD_PARAM_MAP
        assert _FIELD_PARAM_MAP["sensing_keypressed"]["KEY_OPTION"] == "key"
        # Should NOT be in _INPUT_PARAM_MAP
        assert "sensing_keypressed" not in _INPUT_PARAM_MAP

    def test_field_param_map_has_operator_mathop_positional(self) -> None:
        """operator_mathop has OPERATOR as positional arg."""

        assert "operator_mathop" in _FIELD_POSITIONAL_ARGS
        pos_args = _FIELD_POSITIONAL_ARGS["operator_mathop"]
        assert ("OPERATOR", "name") in pos_args
