"""Tests for the Scratch DSL package — expr, builder, category modules, integration."""

from __future__ import annotations

import io

import pytest

from scratch.dsl import (
    Project,
    control,
    data,
    events,
    looks,
    motion,
    operators,
    pen,
    sensing,
)
from scratch.dsl.builder import Script, chain
from scratch.dsl.expr import Reporter
from scratch.sb3.io import load_project
from scratch.vm.target import Target
from scratch.vm.types import Block


# ═════════════════════════════════════════════════════════════════════════
#  Unit — expression construction
# ═════════════════════════════════════════════════════════════════════════


class TestExprConstruction:
    """Verify each expression factory produces correct opcode/inputs/fields."""

    def test_simple_command(self) -> None:
        ex = motion.move(10)
        assert ex.opcode == "motion_movesteps"
        assert ex.inputs["STEPS"].value == 10

    def test_reporter(self) -> None:
        ex = motion.x_position()
        assert ex.opcode == "motion_xposition"

    def test_reporter_as_input(self) -> None:
        ex = motion.x_position()
        bid = ex.as_input()
        assert isinstance(bid, str)
        assert len(bid) > 0
        assert ex.block_id == bid

    def test_literal_input(self) -> None:
        ex = motion.turn_right(15)
        assert ex.opcode == "motion_turnright"
        assert ex.inputs["DEGREES"].value == 15

    def test_string_literal_input(self) -> None:
        ex = looks.say("hello")
        assert ex.opcode == "looks_say"
        assert ex.inputs["MESSAGE"].value == "hello"

    def test_reporter_input(self) -> None:
        ex = motion.move(operators.add(1, 2))
        assert ex.opcode == "motion_movesteps"
        # Input should be an ID string referencing the add reporter
        steps_input = ex.inputs["STEPS"]
        assert isinstance(steps_input.value, str)
        # The reporter should be tracked in shadow_reporters
        assert "STEPS" in ex._shadow_reporters
        assert isinstance(ex._shadow_reporters["STEPS"], Reporter)

    def test_keyword_args(self) -> None:
        ex = motion.goto(x=100, y=200)
        assert ex.opcode == "motion_gotoxy"
        assert ex.inputs["X"].value == 100
        assert ex.inputs["Y"].value == 200

    def test_field_input(self) -> None:
        ex = data.set_variable("score", 10)
        assert ex.opcode == "data_setvariableto"
        assert ex.fields["VARIABLE"].value == "score"
        assert ex.inputs["VALUE"].value == 10

    def test_variable_reporter(self) -> None:
        ex = data.variable("score")
        assert ex.opcode == "data_variable"
        assert ex.fields["VARIABLE"].value == "score"

    def test_c_block_construction(self) -> None:
        """C-shaped blocks use __call__ to attach body."""
        ex = control.repeat(10)
        assert ex.opcode == "control_repeat"
        assert ex._body is None

        # Attach body
        result = ex(motion.move(5), motion.turn_right(15))
        assert result is ex  # returns self
        assert ex._body is not None
        assert len(ex._body) == 2
        assert ex._body[0].opcode == "motion_movesteps"
        assert ex._body[1].opcode == "motion_turnright"

    def test_if_else_construction(self) -> None:
        cond = sensing.touching("edge")
        ex = control.if_else(cond)
        assert ex.opcode == "control_if_else"

        # Add true branch
        ex(looks.say("ouch"))

        # Add false branch
        ex.else_(motion.move(-10))

        assert ex._body is not None
        assert len(ex._body) == 1
        assert ex._body[0].opcode == "looks_say"
        assert ex._body2 is not None
        assert len(ex._body2) == 1
        assert ex._body2[0].opcode == "motion_movesteps"

    def test_if_else_call_returns_self(self) -> None:
        """Verify if_else chain: (cond)(true_branch).else_(false_branch)."""
        cond = sensing.touching("edge")
        ex = control.if_else(cond)(
            looks.say("a"),
        ).else_(
            motion.move(-10),
        )
        assert ex._body is not None
        assert ex._body2 is not None
        assert ex.opcode == "control_if_else"
        assert len(ex._body) == 1
        assert len(ex._body2) == 1

    def test_hat_block(self) -> None:
        ex = events.when_flag_clicked()
        assert ex.opcode == "event_whenflagclicked"

    def test_when_key_pressed(self) -> None:
        ex = events.when_key_pressed("space")
        assert ex.opcode == "event_whenkeypressed"
        assert ex.fields["KEY_OPTION"].value == "space"

    def test_stop_block(self) -> None:
        ex = control.stop("all")
        assert ex.opcode == "control_stop"
        assert ex.fields["STOP_OPTION"].value == "all"

    def test_as_block_creates_reusable_block(self) -> None:
        ex = motion.move(5)
        block = ex.as_block()
        assert isinstance(block, Block)
        assert block.opcode == "motion_movesteps"
        assert block.id == ex.block_id
        assert block.inputs["STEPS"].value == 5

    def test_as_block_ids_are_stable(self) -> None:
        ex = motion.move(5)
        bid1 = ex._ensure_id()
        bid2 = ex._ensure_id()
        assert bid1 == bid2

    def test_c_block_empty_body_as_block(self) -> None:
        ex = control.repeat(10)
        # Call with no args - empty body
        ex()
        block = ex.as_block()
        assert block.opcode == "control_repeat"
        assert "SUBSTACK" not in block.inputs


# ═════════════════════════════════════════════════════════════════════════
#  Unit — builder chain
# ═════════════════════════════════════════════════════════════════════════


class TestChain:
    """Verify chain() correctly links blocks and handles substacks."""

    def test_chain_two_blocks(self) -> None:
        blocks, entry, exit_ = chain([motion.move(5), motion.turn_right(15)])
        assert len(blocks) == 2
        assert entry is not None
        assert exit_ is not None
        assert entry != exit_
        assert entry in blocks
        assert exit_ in blocks
        # Check linking
        assert blocks[entry].next == exit_
        assert blocks[exit_].parent == entry

    def test_chain_single_block(self) -> None:
        blocks, entry, exit_ = chain([motion.move(5)])
        assert entry is not None
        assert exit_ is not None
        assert entry == exit_  # single block: entry == exit
        assert entry in blocks
        assert blocks[entry].next is None
        assert blocks[entry].parent is None

    def test_chain_empty(self) -> None:
        blocks, entry, exit_ = chain([])
        assert blocks == {}
        assert entry is None
        assert exit_ is None

    def test_chain_with_parent(self) -> None:
        parent = "hat_block_id"
        blocks, entry, exit_ = chain([motion.move(5)], parent_id=parent)
        assert entry is not None
        assert entry in blocks
        assert blocks[entry].parent == parent

    def test_chain_c_block_with_substack(self) -> None:
        """A C-block's body should be chained into SUBSTACK inputs."""
        body = control.repeat(3)(motion.move(5))
        blocks, entry, exit_ = chain([body])
        assert entry is not None
        repeat_block = blocks[entry]
        assert repeat_block.opcode == "control_repeat"
        # Should have SUBSTACK input referencing the move block
        assert "SUBSTACK" in repeat_block.inputs
        sub_entry = repeat_block.inputs["SUBSTACK"].value
        assert isinstance(sub_entry, str)
        assert sub_entry in blocks
        assert blocks[sub_entry].opcode == "motion_movesteps"
        assert blocks[sub_entry].parent == entry

    def test_chain_nested_c_block(self) -> None:
        """Nested C-blocks: repeat(forever(move(5)))."""
        inner = control.forever()(motion.move(5))
        outer = control.repeat(10)(inner)

        blocks, entry, exit_ = chain([outer])
        assert entry is not None
        outer_block = blocks[entry]
        assert outer_block.opcode == "control_repeat"
        assert "SUBSTACK" in outer_block.inputs
        inner_id = outer_block.inputs["SUBSTACK"].value
        assert blocks[inner_id].opcode == "control_forever"
        assert "SUBSTACK" in blocks[inner_id].inputs
        move_id = blocks[inner_id].inputs["SUBSTACK"].value
        assert blocks[move_id].opcode == "motion_movesteps"

    def test_chain_if_else(self) -> None:
        """if_else should produce both SUBSTACK and SUBSTACK2."""
        cond = sensing.touching("edge")
        ex = control.if_else(cond)(looks.say("ouch")).else_(motion.move(-10))
        blocks, entry, exit_ = chain([ex])
        assert entry is not None
        if_else_block = blocks[entry]
        assert if_else_block.opcode == "control_if_else"
        assert "SUBSTACK" in if_else_block.inputs
        assert "SUBSTACK2" in if_else_block.inputs

    def test_chain_with_reporter(self) -> None:
        """A reporter used as input should be registered in blocks."""
        ex = motion.move(operators.add(motion.x_position(), 5))
        blocks, entry, exit_ = chain([ex])
        assert entry is not None
        move_block = blocks[entry]
        assert move_block.opcode == "motion_movesteps"
        add_id = move_block.inputs["STEPS"].value
        assert isinstance(add_id, str)
        assert add_id in blocks
        add_block = blocks[add_id]
        assert add_block.opcode == "operator_add"
        # add's NUM1 should reference x_position
        xpos_id = add_block.inputs["NUM1"].value
        assert isinstance(xpos_id, str)
        assert xpos_id in blocks
        assert blocks[xpos_id].opcode == "motion_xposition"
        # add's NUM2 should be literal 5
        assert add_block.inputs["NUM2"].value == 5

    def test_chain_reporter_only_in_hat(self) -> None:
        """Reporters on a hat should be registered too."""
        hat = events.when_greater_than("loudness", operators.add(1, 2))
        script = Script(hat=hat)
        t = Target("Test", is_stage=True)
        script.build(t)
        # Should contain hat + add reporter
        assert len(t.blocks) >= 2
        add_blocks = [b for b in t.blocks.values() if b.opcode == "operator_add"]
        assert len(add_blocks) == 1


# ═════════════════════════════════════════════════════════════════════════
#  Unit — Script.build()
# ═════════════════════════════════════════════════════════════════════════


class TestScriptBuild:
    """Script.build() should populate Target.blocks correctly."""

    def test_empty_body(self) -> None:
        hat = events.when_flag_clicked()
        script = Script(hat=hat)
        t = Target("Sprite")
        script.build(t)
        assert len(t.blocks) == 1
        hat_block = t.blocks[hat._ensure_id()]
        assert hat_block.top_level
        assert hat_block.next is None

    def test_single_body(self) -> None:
        script = Script(hat=events.when_flag_clicked(), body=[motion.move(10)])
        t = Target("Sprite")
        script.build(t)
        hat_id = script.hat._ensure_id()
        assert hat_id in t.blocks
        move_id = script.body[0]._ensure_id()
        assert move_id in t.blocks
        assert t.blocks[hat_id].next == move_id

    def test_multiple_body(self) -> None:
        script = Script(
            hat=events.when_flag_clicked(),
            body=[motion.move(10), motion.turn_right(15)],
        )
        t = Target("Sprite")
        script.build(t)
        assert len(t.blocks) == 3  # hat + 2 body
        hat_id = script.hat._ensure_id()
        move_id = script.body[0]._ensure_id()
        turn_id = script.body[1]._ensure_id()
        assert t.blocks[hat_id].next == move_id
        assert t.blocks[move_id].next == turn_id
        assert t.blocks[turn_id].next is None

    def test_c_block_with_substack(self) -> None:
        script = Script(
            hat=events.when_flag_clicked(),
            body=[control.repeat(3)(motion.move(5))],
        )
        t = Target("Sprite")
        script.build(t)
        hat_id = script.hat._ensure_id()
        repeat_id = script.body[0]._ensure_id()
        assert script.body[0]._body is not None
        sub_id = script.body[0]._body[0]._ensure_id()

    def test_variable_field_map(self) -> None:
        var_map = {"score": "vid1"}
        ex = data.set_variable("score", 10)
        blocks, entry, _ = chain([ex], var_map=var_map)
        assert entry is not None
        block = blocks[entry]

    def test_variable_field_missing_name(self) -> None:
        """Unknown variable name -> Field.id stays None."""
        var_map = {"existing": "vid1"}
        ex = data.set_variable("unknown", 10)
        blocks, entry, _ = chain([ex], var_map=var_map)
        assert entry is not None
        block = blocks[entry]


# ═════════════════════════════════════════════════════════════════════════
#  Unit -- category functions
# ═════════════════════════════════════════════════════════════════════════


class TestCategoryMotion:
    """Smoke tests for motion category functions."""

    def test_move_defaults(self) -> None:
        ex = motion.move()
        assert ex.opcode == "motion_movesteps"
        assert ex.inputs["STEPS"].value == 10

    def test_defaults(self) -> None:
        assert motion.turn_right().inputs["DEGREES"].value == 15
        assert motion.turn_left().inputs["DEGREES"].value == 15
        assert motion.goto().inputs["X"].value == 0
        assert motion.goto().inputs["Y"].value == 0

    def test_reporters(self) -> None:
        assert motion.x_position().opcode == "motion_xposition"
        assert motion.y_position().opcode == "motion_yposition"
        assert motion.direction().opcode == "motion_direction"


class TestCategoryControl:
    def test_forever_opcode(self) -> None:
        assert control.forever().opcode == "control_forever"

    def test_repeat_defaults(self) -> None:
        assert control.repeat().inputs["TIMES"].value == 10

    def test_if_opcode(self) -> None:
        ex = control.if_(sensing.touching("edge"))
        assert ex.opcode == "control_if"

    def test_if_else_opcode(self) -> None:
        ex = control.if_else(sensing.touching("edge"))
        assert ex.opcode == "control_if_else"

    def test_wait_defaults(self) -> None:
        assert control.wait().inputs["DURATION"].value == 1

    def test_repeat_until_opcode(self) -> None:
        ex = control.repeat_until(sensing.key_pressed("space"))
        assert ex.opcode == "control_repeat_until"


class TestCategoryData:
    def test_set_variable(self) -> None:
        ex = data.set_variable("score", 10)
        assert ex.opcode == "data_setvariableto"
        assert ex.fields["VARIABLE"].value == "score"
        assert ex.inputs["VALUE"].value == 10

    def test_variable_reporter(self) -> None:
        ex = data.variable("score")
        assert ex.opcode == "data_variable"
        assert ex.fields["VARIABLE"].value == "score"

    def test_add_to_list(self) -> None:
        ex = data.add_to_list("my_list", "item")
        assert ex.opcode == "data_addtolist"
        assert ex.fields["LIST"].variable_type == "list"


class TestCategoryOperators:
    def test_add_reporter(self) -> None:
        ex = operators.add(1, 2)
        assert ex.opcode == "operator_add"
        assert ex.inputs["NUM1"].value == 1
        assert ex.inputs["NUM2"].value == 2

    def test_reporter_nesting(self) -> None:
        ex = operators.add(motion.x_position(), 5)
        assert ex.opcode == "operator_add"
        assert "NUM1" in ex._shadow_reporters
        assert isinstance(ex._shadow_reporters["NUM1"], Reporter)
        assert ex.inputs["NUM2"].value == 5

    def test_keyword_collision_underscore(self) -> None:
        ex = operators.random(from_=1, to=10)
        assert ex.opcode == "operator_random"
        assert ex.inputs["FROM"].value == 1
        assert ex.inputs["TO"].value == 10

    def test_and_not_opcodes(self) -> None:
        ex = operators.and_(sensing.touching("edge"), sensing.key_pressed("space"))
        assert ex.opcode == "operator_and"
        assert operators.not_(sensing.key_pressed("a")).opcode == "operator_not"


class TestCategorySensing:
    def test_touching_string(self) -> None:
        ex = sensing.touching("edge")
        assert ex.opcode == "sensing_touchingobject"
        assert ex.fields["TOUCHINGOBJECTMENU"].value == "edge"

    def test_touching_reporter(self) -> None:
        ex = sensing.touching(data.variable("target"))
        assert ex.opcode == "sensing_touchingobject"
        assert "TOUCHINGOBJECTMENU" in ex._shadow_reporters


class TestCategoryPen:
    def test_pen_down_up(self) -> None:
        assert pen.pen_down().opcode == "pen_penDown"
        assert pen.pen_up().opcode == "pen_penUp"
        assert pen.pen_clear().opcode == "pen_penClear"
        assert pen.stamp().opcode == "pen_stamp"


# ═════════════════════════════════════════════════════════════════════════
#  Integration -- Project
# ═════════════════════════════════════════════════════════════════════════


class TestProject:
    def test_project_create(self) -> None:
        project = Project("Test")
        assert project.name == "Test"
        assert project.stage is not None
        assert project.stage.name == "Stage"
        assert project.stage.is_stage

    def test_sprite_creation(self) -> None:
        project = Project()
        s = project.sprite("Cat")
        assert s.name == "Cat"
        assert not s.is_stage

    def test_build_runtime_empty(self) -> None:
        project = Project()
        rt = project.build_runtime()
        assert len(rt.targets) == 1  # stage only
        stage = rt.targets[0]
        assert stage.is_stage
        assert stage.name == "Stage"

    def test_build_runtime_with_sprites(self) -> None:
        project = Project()
        project.sprite("Cat")
        project.sprite("Dog")
        rt = project.build_runtime()
        assert len(rt.targets) == 3  # stage + 2 sprites
        assert rt.targets[1].name == "Cat"
        assert rt.targets[2].name == "Dog"

    def test_build_runtime_variables(self) -> None:
        project = Project()
        s = project.sprite("Cat")
        s.var("score", 0)
        s.var("lives", 3)
        rt = project.build_runtime()
        target = rt.get_target_by_name("Cat")
        assert target is not None
        assert len(target.variables) == 2
        vars_by_name = {v.name: v for v in target.variables.values()}
        assert vars_by_name["score"].value == 0
        assert vars_by_name["lives"].value == 3

    def test_duplicate_variable_error(self) -> None:
        s = Project().sprite("Cat")
        s.var("score", 0)
        with pytest.raises(ValueError, match="already exists"):
            s.var("score", 1)

    def test_when_flag_clicked_integration(self) -> None:
        project = Project()
        s = project.sprite("Cat")
        s.when_flag_clicked(motion.move(10), motion.turn_right(15))
        rt = project.build_runtime()
        target = rt.get_target_by_name("Cat")
        assert target is not None
        assert len(target.blocks) == 3  # hat + move + turn

    def test_when_key_pressed_integration(self) -> None:
        project = Project()
        s = project.sprite("Cat")
        s.when_key_pressed("space")(motion.move(10))
        rt = project.build_runtime()
        target = rt.get_target_by_name("Cat")
        assert target is not None
        assert len(target.blocks) == 2  # hat + move

    def test_variable_in_script(self) -> None:
        project = Project()
        s = project.sprite("Cat")
        s.var("score", 0)
        s.when_flag_clicked(
            data.set_variable("score", operators.add(data.variable("score"), 1)),
        )
        rt = project.build_runtime()
        target = rt.get_target_by_name("Cat")
        assert target is not None
        # Hat + set_variable + add reporter + variable reporter
        assert len(target.blocks) >= 3

    def test_variable_field_resolved(self) -> None:
        """Build a project with a variable and verify Field.id is set."""
        project = Project()
        s = project.sprite("Cat")
        s.var("score", 0)
        s.when_flag_clicked(
            data.set_variable("score", 10),
            data.change_variable("score", 5),
        )
        rt = project.build_runtime()
        target = rt.get_target_by_name("Cat")
        assert target is not None
        # Find set_variable block
        for block in target.blocks.values():
            if block.opcode == "data_setvariableto":
                assert block.fields["VARIABLE"].value == "score"
                assert block.fields["VARIABLE"].id is not None
                break
        else:
            pytest.fail("data_setvariableto block not found")


# ═════════════════════════════════════════════════════════════════════════
#  Integration -- save -> load round-trip
# ═════════════════════════════════════════════════════════════════════════


class TestRoundTrip:
    """Build a project, save to BytesIO, reload, and verify blocks match."""

    def test_empty_project(self) -> None:
        project = Project("Test")
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        rt = load_project(buf)
        assert len(rt.targets) == 1
        assert rt.targets[0].name == "Stage"

    def test_simple_script(self) -> None:
        project = Project()
        s = project.sprite("Cat")
        s.when_flag_clicked(motion.move(10), motion.turn_right(15))
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        rt = load_project(buf)
        target = rt.get_target_by_name("Cat")
        assert target is not None
        # Should have 3 blocks: hat + move + turn
        assert len(target.blocks) == 3

    def test_with_variables(self) -> None:
        project = Project()
        s = project.sprite("Cat")
        s.var("score", 0)
        s.when_flag_clicked(data.set_variable("score", 10))
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        rt = load_project(buf)
        target = rt.get_target_by_name("Cat")
        assert target is not None
        # Variable should exist with default value 0
        vars_by_name = {v.name: v for v in target.variables.values()}
        assert "score" in vars_by_name
        assert vars_by_name["score"].value == 0

    def test_reporter_nesting_round_trip(self) -> None:
        """Nested reporters survive save/load."""
        project = Project()
        s = project.sprite("Cat")
        s.var("score", 0)
        s.when_flag_clicked(
            data.set_variable(
                "score",
                operators.add(data.variable("score"), 1),
            ),
        )
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        rt = load_project(buf)
        target = rt.get_target_by_name("Cat")
        assert target is not None
        # Find set_variable block
        set_blocks = [
            b for b in target.blocks.values() if b.opcode == "data_setvariableto"
        ]
        assert len(set_blocks) == 1
        set_block = set_blocks[0]
        add_id = set_block.inputs["VALUE"].value
        assert isinstance(add_id, str)
        assert add_id in target.blocks
        assert target.blocks[add_id].opcode == "operator_add"

    def test_c_block_round_trip(self) -> None:
        """C-blocks with substacks survive save/load."""
        project = Project()
        s = project.sprite("Cat")
        s.when_flag_clicked(
            control.repeat(10)(motion.move(5)),
        )
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        rt = load_project(buf)
        target = rt.get_target_by_name("Cat")
        assert target is not None
        repeat_blocks = [
            b for b in target.blocks.values() if b.opcode == "control_repeat"
        ]
        assert len(repeat_blocks) == 1
        repeat_block = repeat_blocks[0]
        assert "SUBSTACK" in repeat_block.inputs
        sub_id = repeat_block.inputs["SUBSTACK"].value
        assert isinstance(sub_id, str)
        assert sub_id in target.blocks
        assert target.blocks[sub_id].opcode == "motion_movesteps"
