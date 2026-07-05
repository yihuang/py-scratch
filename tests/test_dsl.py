"""Tests for the Scratch DSL package — expr, builder, category modules, integration."""

from __future__ import annotations

import io
import zipfile

import pytest

import json

from scratch.dsl import (
    Project,
    control,
    data,
    events,
    looks,
    motion,
    operators,
    pen,
    procedures,
    sensing,
    sound,
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
        assert ex.opcode == 'motion_movesteps'
        assert ex.inputs['STEPS'].value == 10

    def test_reporter(self) -> None:
        ex = motion.x_position()
        assert ex.opcode == 'motion_xposition'

    def test_reporter_as_input(self) -> None:
        ex = motion.x_position()
        bid = ex.as_input()
        assert isinstance(bid, str)
        assert len(bid) > 0
        assert ex.block_id == bid

    def test_literal_input(self) -> None:
        ex = motion.turn_right(15)
        assert ex.opcode == 'motion_turnright'
        assert ex.inputs['DEGREES'].value == 15

    def test_string_literal_input(self) -> None:
        ex = looks.say('hello')
        assert ex.opcode == 'looks_say'
        assert ex.inputs['MESSAGE'].value == 'hello'

    def test_reporter_input(self) -> None:
        ex = motion.move(operators.add(1, 2))
        assert ex.opcode == 'motion_movesteps'
        # Input should be an ID string referencing the add reporter
        steps_input = ex.inputs['STEPS']
        assert isinstance(steps_input.value, str)
        # The reporter should be tracked in shadow_reporters
        assert 'STEPS' in ex._shadow_reporters
        assert isinstance(ex._shadow_reporters['STEPS'], Reporter)

    def test_keyword_args(self) -> None:
        ex = motion.goto(x=100, y=200)
        assert ex.opcode == 'motion_gotoxy'
        assert ex.inputs['X'].value == 100
        assert ex.inputs['Y'].value == 200

    def test_field_input(self) -> None:
        ex = data.set_variable('score', 10)
        assert ex.opcode == 'data_setvariableto'
        assert ex.fields['VARIABLE'].value == 'score'
        assert ex.inputs['VALUE'].value == 10

    def test_variable_reporter(self) -> None:
        ex = data.variable('score')
        assert ex.opcode == 'data_variable'
        assert ex.fields['VARIABLE'].value == 'score'

    def test_c_block_construction(self) -> None:
        """C-shaped blocks use __call__ to attach body."""
        ex = control.repeat(10)
        assert ex.opcode == 'control_repeat'
        assert ex._body is None

        # Attach body
        result = ex(motion.move(5), motion.turn_right(15))
        assert result is ex  # returns self
        assert ex._body is not None
        assert len(ex._body) == 2
        assert ex._body[0].opcode == 'motion_movesteps'
        assert ex._body[1].opcode == 'motion_turnright'

    def test_if_else_construction(self) -> None:
        cond = sensing.touching('edge')
        ex = control.if_else(cond)
        assert ex.opcode == 'control_if_else'

        # Add true branch
        ex(looks.say('ouch'))

        # Add false branch
        ex.else_(motion.move(-10))

        assert ex._body is not None
        assert len(ex._body) == 1
        assert ex._body[0].opcode == 'looks_say'
        assert ex._body2 is not None
        assert len(ex._body2) == 1
        assert ex._body2[0].opcode == 'motion_movesteps'

    def test_if_else_call_returns_self(self) -> None:
        """Verify if_else chain: (cond)(true_branch).else_(false_branch)."""
        cond = sensing.touching('edge')
        ex = control.if_else(cond)(
            looks.say('a'),
        ).else_(
            motion.move(-10),
        )
        assert ex._body is not None
        assert ex._body2 is not None
        assert ex.opcode == 'control_if_else'
        assert len(ex._body) == 1
        assert len(ex._body2) == 1

    def test_hat_block(self) -> None:
        ex = events.when_flag_clicked()
        assert ex.opcode == 'event_whenflagclicked'

    def test_when_key_pressed(self) -> None:
        ex = events.when_key_pressed('space')
        assert ex.opcode == 'event_whenkeypressed'
        assert ex.fields['KEY_OPTION'].value == 'space'

    def test_stop_block(self) -> None:
        ex = control.stop('all')
        assert ex.opcode == 'control_stop'
        assert ex.fields['STOP_OPTION'].value == 'all'

    def test_as_block_creates_reusable_block(self) -> None:
        ex = motion.move(5)
        block = ex.as_block()
        assert isinstance(block, Block)
        assert block.opcode == 'motion_movesteps'
        assert block.id == ex.block_id
        assert block.inputs['STEPS'].value == 5

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
        assert block.opcode == 'control_repeat'
        assert 'SUBSTACK' not in block.inputs


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
        parent = 'hat_block_id'
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
        assert repeat_block.opcode == 'control_repeat'
        # Should have SUBSTACK input referencing the move block
        assert 'SUBSTACK' in repeat_block.inputs
        sub_entry = repeat_block.inputs['SUBSTACK'].value
        assert isinstance(sub_entry, str)
        assert sub_entry in blocks
        assert blocks[sub_entry].opcode == 'motion_movesteps'
        assert blocks[sub_entry].parent == entry

    def test_chain_nested_c_block(self) -> None:
        """Nested C-blocks: repeat(forever(move(5)))."""
        inner = control.forever()(motion.move(5))
        outer = control.repeat(10)(inner)

        blocks, entry, exit_ = chain([outer])
        assert entry is not None
        outer_block = blocks[entry]
        assert outer_block.opcode == 'control_repeat'
        assert 'SUBSTACK' in outer_block.inputs
        inner_id = outer_block.inputs['SUBSTACK'].value
        assert blocks[inner_id].opcode == 'control_forever'
        assert 'SUBSTACK' in blocks[inner_id].inputs
        move_id = blocks[inner_id].inputs['SUBSTACK'].value
        assert blocks[move_id].opcode == 'motion_movesteps'

    def test_chain_if_else(self) -> None:
        """if_else should produce both SUBSTACK and SUBSTACK2."""
        cond = sensing.touching('edge')
        ex = control.if_else(cond)(looks.say('ouch')).else_(motion.move(-10))
        blocks, entry, exit_ = chain([ex])
        assert entry is not None
        if_else_block = blocks[entry]
        assert if_else_block.opcode == 'control_if_else'
        assert 'SUBSTACK' in if_else_block.inputs
        assert 'SUBSTACK2' in if_else_block.inputs

    def test_chain_with_reporter(self) -> None:
        """A reporter used as input should be registered in blocks."""
        ex = motion.move(operators.add(motion.x_position(), 5))
        blocks, entry, exit_ = chain([ex])
        assert entry is not None
        move_block = blocks[entry]
        assert move_block.opcode == 'motion_movesteps'
        add_id = move_block.inputs['STEPS'].value
        assert isinstance(add_id, str)
        assert add_id in blocks
        add_block = blocks[add_id]
        assert add_block.opcode == 'operator_add'
        # add's NUM1 should reference x_position
        xpos_id = add_block.inputs['NUM1'].value
        assert isinstance(xpos_id, str)
        assert xpos_id in blocks
        assert blocks[xpos_id].opcode == 'motion_xposition'
        # add's NUM2 should be literal 5
        assert add_block.inputs['NUM2'].value == 5

    def test_chain_reporter_only_in_hat(self) -> None:
        """Reporters on a hat should be registered too."""
        hat = events.when_greater_than('loudness', operators.add(1, 2))
        script = Script(hat=hat)
        t = Target('Test', is_stage=True)
        script.build(t)
        # Should contain hat + add reporter
        assert len(t.blocks) >= 2
        add_blocks = [b for b in t.blocks.values() if b.opcode == 'operator_add']
        assert len(add_blocks) == 1


# ═════════════════════════════════════════════════════════════════════════
#  Unit — Script.build()
# ═════════════════════════════════════════════════════════════════════════


class TestScriptBuild:
    """Script.build() should populate Target.blocks correctly."""

    def test_empty_body(self) -> None:
        hat = events.when_flag_clicked()
        script = Script(hat=hat)
        t = Target('Sprite')
        script.build(t)
        assert len(t.blocks) == 1
        hat_block = t.blocks[hat._ensure_id()]
        assert hat_block.top_level
        assert hat_block.next is None

    def test_single_body(self) -> None:
        script = Script(hat=events.when_flag_clicked(), body=[motion.move(10)])
        t = Target('Sprite')
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
        t = Target('Sprite')
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
        t = Target('Sprite')
        script.build(t)
        hat_id = script.hat._ensure_id()
        repeat_id = script.body[0]._ensure_id()
        assert script.body[0]._body is not None
        sub_id = script.body[0]._body[0]._ensure_id()

    def test_variable_field_map(self) -> None:
        var_map = {'score': 'vid1'}
        ex = data.set_variable('score', 10)
        blocks, entry, _ = chain([ex], var_map=var_map)
        assert entry is not None
        block = blocks[entry]

    def test_variable_field_missing_name(self) -> None:
        """Unknown variable name -> Field.id stays None."""
        var_map = {'existing': 'vid1'}
        ex = data.set_variable('unknown', 10)
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
        assert ex.opcode == 'motion_movesteps'
        assert ex.inputs['STEPS'].value == 10

    def test_defaults(self) -> None:
        assert motion.turn_right().inputs['DEGREES'].value == 15
        assert motion.turn_left().inputs['DEGREES'].value == 15
        assert motion.goto().inputs['X'].value == 0
        assert motion.goto().inputs['Y'].value == 0

    def test_reporters(self) -> None:
        assert motion.x_position().opcode == 'motion_xposition'
        assert motion.y_position().opcode == 'motion_yposition'
        assert motion.direction().opcode == 'motion_direction'


class TestCategoryControl:
    def test_forever_opcode(self) -> None:
        assert control.forever().opcode == 'control_forever'

    def test_repeat_defaults(self) -> None:
        # TIMES uses WHOLE_NUMBER type: [6, '10']
        assert control.repeat().inputs['TIMES'].value[1] == '10'

    def test_if_opcode(self) -> None:
        ex = control.if_(sensing.touching('edge'))
        assert ex.opcode == 'control_if'

    def test_if_else_opcode(self) -> None:
        ex = control.if_else(sensing.touching('edge'))
        assert ex.opcode == 'control_if_else'

    def test_wait_defaults(self) -> None:
        # DURATION uses POSITIVE_NUMBER type: [5, '1']
        assert control.wait().inputs['DURATION'].value[1] == '1'

    def test_repeat_until_opcode(self) -> None:
        ex = control.repeat_until(sensing.key_pressed('space'))
        assert ex.opcode == 'control_repeat_until'


class TestCategoryData:
    def test_set_variable(self) -> None:
        ex = data.set_variable('score', 10)
        assert ex.opcode == 'data_setvariableto'
        assert ex.fields['VARIABLE'].value == 'score'
        assert ex.inputs['VALUE'].value == 10

    def test_variable_reporter(self) -> None:
        ex = data.variable('score')
        assert ex.opcode == 'data_variable'
        assert ex.fields['VARIABLE'].value == 'score'

    def test_add_to_list(self) -> None:
        ex = data.add_to_list('my_list', 'item')
        assert ex.opcode == 'data_addtolist'
        assert ex.fields['LIST'].variable_type == 'list'


class TestCategoryOperators:
    def test_add_reporter(self) -> None:
        ex = operators.add(1, 2)
        assert ex.opcode == 'operator_add'
        assert ex.inputs['NUM1'].value == 1
        assert ex.inputs['NUM2'].value == 2

    def test_reporter_nesting(self) -> None:
        ex = operators.add(motion.x_position(), 5)
        assert ex.opcode == 'operator_add'
        assert 'NUM1' in ex._shadow_reporters
        assert isinstance(ex._shadow_reporters['NUM1'], Reporter)
        assert ex.inputs['NUM2'].value == 5

    def test_keyword_collision_underscore(self) -> None:
        ex = operators.random(from_=1, to=10)
        assert ex.opcode == 'operator_random'
        assert ex.inputs['FROM'].value == 1
        assert ex.inputs['TO'].value == 10

    def test_and_not_opcodes(self) -> None:
        ex = operators.and_(sensing.touching('edge'), sensing.key_pressed('space'))
        assert ex.opcode == 'operator_and'
        assert operators.not_(sensing.key_pressed('a')).opcode == 'operator_not'


class TestCategorySensing:
    def test_touching_string(self) -> None:
        ex = sensing.touching('edge')
        assert ex.opcode == 'sensing_touchingobject'
        assert ex.fields['TOUCHINGOBJECTMENU'].value == 'edge'

    def test_touching_reporter(self) -> None:
        ex = sensing.touching(data.variable('target'))
        assert ex.opcode == 'sensing_touchingobject'
        # Variable reporter is now inlined via variable_name, not shadow_reporter
        assert ex.inputs['TOUCHINGOBJECTMENU'].variable_name == 'target'


class TestCategoryPen:
    def test_pen_down_up(self) -> None:
        assert pen.pen_down().opcode == 'pen_penDown'
        assert pen.pen_up().opcode == 'pen_penUp'
        assert pen.pen_clear().opcode == 'pen_clear'
        assert pen.stamp().opcode == 'pen_stamp'


# ═════════════════════════════════════════════════════════════════════════
#  Integration -- Project
# ═════════════════════════════════════════════════════════════════════════


class TestProject:
    def test_project_create(self) -> None:
        project = Project('Test')
        assert project.name == 'Test'
        assert project.stage is not None
        assert project.stage.name == 'Stage'
        assert project.stage.is_stage

    def test_sprite_creation(self) -> None:
        project = Project()
        s = project.sprite('Cat')
        assert s.name == 'Cat'
        assert not s.is_stage

    def test_build_runtime_empty(self) -> None:
        project = Project()
        rt = project.build_runtime()
        assert len(rt.targets) == 1  # stage only
        stage = rt.targets[0]
        assert stage.is_stage
        assert stage.name == 'Stage'

    def test_build_runtime_with_sprites(self) -> None:
        project = Project()
        project.sprite('Cat')
        project.sprite('Dog')
        rt = project.build_runtime()
        assert len(rt.targets) == 3  # stage + 2 sprites
        assert rt.targets[1].name == 'Cat'
        assert rt.targets[2].name == 'Dog'

    def test_build_runtime_variables(self) -> None:
        project = Project()
        s = project.sprite('Cat')
        s.var('score', 0)
        s.var('lives', 3)
        rt = project.build_runtime()
        target = rt.get_target_by_name('Cat')
        assert target is not None
        assert len(target.variables) == 2
        vars_by_name = {v.name: v for v in target.variables.values()}
        assert vars_by_name['score'].value == 0
        assert vars_by_name['lives'].value == 3

    def test_duplicate_variable_error(self) -> None:
        s = Project().sprite('Cat')
        s.var('score', 0)
        with pytest.raises(ValueError, match='already exists'):
            s.var('score', 1)

    def test_when_flag_clicked_integration(self) -> None:
        project = Project()
        s = project.sprite('Cat')
        s.when_flag_clicked(motion.move(10), motion.turn_right(15))
        rt = project.build_runtime()
        target = rt.get_target_by_name('Cat')
        assert target is not None
        assert len(target.blocks) == 3  # hat + move + turn

    def test_when_key_pressed_integration(self) -> None:
        project = Project()
        s = project.sprite('Cat')
        s.when_key_pressed('space')(motion.move(10))
        rt = project.build_runtime()
        target = rt.get_target_by_name('Cat')
        assert target is not None
        assert len(target.blocks) == 2  # hat + move

    def test_variable_in_script(self) -> None:
        project = Project()
        s = project.sprite('Cat')
        s.var('score', 0)
        s.when_flag_clicked(
            data.set_variable('score', operators.add(data.variable('score'), 1)),
        )
        rt = project.build_runtime()
        target = rt.get_target_by_name('Cat')
        assert target is not None
        # Hat + set_variable + add reporter + variable reporter
        assert len(target.blocks) >= 3

    def test_variable_field_resolved(self) -> None:
        """Build a project with a variable and verify Field.id is set."""
        project = Project()
        s = project.sprite('Cat')
        s.var('score', 0)
        s.when_flag_clicked(
            data.set_variable('score', 10),
            data.change_variable('score', 5),
        )
        rt = project.build_runtime()
        target = rt.get_target_by_name('Cat')
        assert target is not None
        # Find set_variable block
        for block in target.blocks.values():
            if block.opcode == 'data_setvariableto':
                assert block.fields['VARIABLE'].value == 'score'
                assert block.fields['VARIABLE'].id is not None
                break
        else:
            pytest.fail('data_setvariableto block not found')


# ═════════════════════════════════════════════════════════════════════════
#  Integration -- save -> load round-trip
# ═════════════════════════════════════════════════════════════════════════


class TestRoundTrip:
    """Build a project, save to BytesIO, reload, and verify blocks match."""

    def test_empty_project(self) -> None:
        project = Project('Test')
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        rt = load_project(buf)
        assert len(rt.targets) == 1
        assert rt.targets[0].name == 'Stage'

    def test_simple_script(self) -> None:
        project = Project()
        s = project.sprite('Cat')
        s.when_flag_clicked(motion.move(10), motion.turn_right(15))
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        rt = load_project(buf)
        target = rt.get_target_by_name('Cat')
        assert target is not None
        # Should have 3 blocks: hat + move + turn
        assert len(target.blocks) == 3

    def test_with_variables(self) -> None:
        project = Project()
        s = project.sprite('Cat')
        s.var('score', 0)
        s.when_flag_clicked(data.set_variable('score', 10))
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        rt = load_project(buf)
        target = rt.get_target_by_name('Cat')
        assert target is not None
        # Variable should exist with default value 0
        vars_by_name = {v.name: v for v in target.variables.values()}
        assert 'score' in vars_by_name
        assert vars_by_name['score'].value == 0

    def test_reporter_nesting_round_trip(self) -> None:
        """Nested reporters survive save/load."""
        project = Project()
        s = project.sprite('Cat')
        s.var('score', 0)
        s.when_flag_clicked(
            data.set_variable(
                'score',
                operators.add(data.variable('score'), 1),
            ),
        )
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        rt = load_project(buf)
        target = rt.get_target_by_name('Cat')
        assert target is not None
        # Find set_variable block
        set_blocks = [b for b in target.blocks.values() if b.opcode == 'data_setvariableto']
        assert len(set_blocks) == 1
        set_block = set_blocks[0]
        add_id = set_block.inputs['VALUE'].value
        assert isinstance(add_id, str)
        assert add_id in target.blocks
        assert target.blocks[add_id].opcode == 'operator_add'

    def test_c_block_round_trip(self) -> None:
        """C-blocks with substacks survive save/load."""
        project = Project()
        s = project.sprite('Cat')
        s.when_flag_clicked(
            control.repeat(10)(motion.move(5)),
        )
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        rt = load_project(buf)
        target = rt.get_target_by_name('Cat')
        assert target is not None
        repeat_blocks = [b for b in target.blocks.values() if b.opcode == 'control_repeat']
        assert len(repeat_blocks) == 1
        repeat_block = repeat_blocks[0]
        assert 'SUBSTACK' in repeat_block.inputs
        sub_id = repeat_block.inputs['SUBSTACK'].value
        assert isinstance(sub_id, str)
        assert sub_id in target.blocks
        assert target.blocks[sub_id].opcode == 'motion_movesteps'

    def test_sprite_define(self) -> None:
        """sprite.define() registers a procedure definition as a top-level hat."""
        project = Project('ProcTest')
        s = project.sprite('Cat')
        s.define('greet %s', 'name')(
            motion.move(10),
        )
        rt = project.build_runtime()
        target = rt.get_target_by_name('Cat')
        assert target is not None
        def_blocks = [b for b in target.blocks.values() if b.opcode == 'procedures_definition']
        assert len(def_blocks) == 1
        def_block = def_blocks[0]
        assert def_block.top_level is True
        # Body should be attached to the definition
        assert def_block.next is not None
        assert target.blocks[def_block.next].opcode == 'motion_movesteps'

    def test_sprite_define_and_call(self) -> None:
        """sprite.define() + procedures.call() produces a valid sb3."""
        project = Project('ProcTest')
        s = project.sprite('Cat')
        s.define('jump %n', 'height')(
            motion.change_y(procedures.arg('height')),
        )
        s.when_flag_clicked(
            procedures.call('jump %n', 50),
        )
        buf = io.BytesIO()
        project.save(buf)
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            data = json.loads(zf.read('project.json'))
        # Both definition and call should be present
        cat_target = data['targets'][1]
        def_blocks = [
            b
            for b in cat_target['blocks'].values()
            if isinstance(b, dict) and b.get('opcode') == 'procedures_definition'
        ]
        call_blocks = [
            b
            for b in cat_target['blocks'].values()
            if isinstance(b, dict) and b.get('opcode') == 'procedures_call'
        ]
        assert len(def_blocks) == 1
        assert len(call_blocks) == 1


# ═════════════════════════════════════════════════════════════════════════
#  Category -- Procedures (custom blocks)
# ═════════════════════════════════════════════════════════════════════════


class TestCategoryProcedures:
    """procedures.define(), procedures.arg(), procedures.call()."""

    def test_define_no_params(self) -> None:

        ex = procedures.define('my_block')
        assert ex.opcode == 'procedures_definition'
        assert ex._mutation is not None
        assert ex._mutation.proccode == 'my_block'
        assert ex._mutation.argumentids == '[]'

    def test_define_with_params(self) -> None:

        ex = procedures.define('move %n %s', 'steps', 'direction')
        assert ex.opcode == 'procedures_definition'
        assert ex._mutation is not None
        assert ex._mutation.proccode == 'move %n %s'

        names = json.loads(ex._mutation.argumentnames)
        assert names == ['steps', 'direction']

    def test_define_with_body(self) -> None:

        ex = procedures.define('my_block')
        ex(motion.move(10), motion.turn_right(90))
        assert ex._body is not None
        assert len(ex._body) == 2
        assert ex._body[0].opcode == 'motion_movesteps'
        assert ex._body[1].opcode == 'motion_turnright'

    def test_call_no_args(self) -> None:

        ex = procedures.call('my_block')
        assert ex.opcode == 'procedures_call'
        assert ex._mutation is not None
        assert ex._mutation.proccode == 'my_block'

    def test_call_with_args(self) -> None:

        ex = procedures.call('add %n %n', 3, 5)
        assert ex.opcode == 'procedures_call'
        assert ex._mutation is not None
        arg_ids = json.loads(ex._mutation.argumentids)
        assert len(arg_ids) == 2
        assert arg_ids[0] in ex.inputs
        assert arg_ids[1] in ex.inputs
        # Procedure call args use SHADOW_FLAG with TEXT primitives
        assert ex.inputs[arg_ids[0]].value == [10, '3']
        assert ex.inputs[arg_ids[1]].value == [10, '5']

    def test_call_with_reporter_arg(self) -> None:

        ex = procedures.call('say %s', data.variable('score'))
        assert ex.opcode == 'procedures_call'
        assert ex._mutation is not None
        arg_ids = json.loads(ex._mutation.argumentids)
        assert len(arg_ids) == 1
        aid = arg_ids[0]
        assert aid in ex.inputs
        # Reporter is stored as shadow
        assert aid in ex._shadow_reporters

    def test_arg_reporter(self) -> None:

        ex = procedures.arg('param1')
        assert ex.opcode == 'argument_reporter_string_number'
        assert ex.fields['VALUE'].value == 'param1'

    def test_define_builds_runtime(self) -> None:
        """Integration: define + call via builder."""

        project = Project('ProcTest')
        s = project.sprite('Cat')
        s.when_flag_clicked(
            procedures.call('hello'),
        )
        # Add definition as a Script
        hat = procedures.define('hello')
        hat(motion.move(10))
        script = Script(hat)
        target = project.build_runtime().get_target_by_name('Cat')
        assert target is not None
        script.build(target)
        # Check both blocks exist
        def_blocks = [b for b in target.blocks.values() if b.opcode == 'procedures_definition']
        assert len(def_blocks) == 1
        call_blocks = [b for b in target.blocks.values() if b.opcode == 'procedures_call']
        assert len(call_blocks) == 1


class TestCategoryLooks:
    """looks.* blocks."""

    def test_show_hide(self) -> None:
        assert looks.show().opcode == 'looks_show'
        assert looks.hide().opcode == 'looks_hide'

    def test_say(self) -> None:
        ex = looks.say('hello')
        assert ex.opcode == 'looks_say'
        assert ex.inputs['MESSAGE'].value == 'hello'

    def test_say_for_seconds(self) -> None:
        ex = looks.say_for_seconds('hi', 2)
        assert ex.opcode == 'looks_sayforsecs'
        assert ex.inputs['MESSAGE'].value == 'hi'
        assert ex.inputs['SECS'].value == 2

    def test_think(self) -> None:
        ex = looks.think('hmm')
        assert ex.opcode == 'looks_think'

    def test_switch_costume(self) -> None:
        ex = looks.switch_costume_to('costume1')
        assert ex.opcode == 'looks_switchcostumeto'

    def test_next_costume(self) -> None:
        assert looks.next_costume().opcode == 'looks_nextcostume'

    def test_switch_backdrop(self) -> None:
        ex = looks.switch_backdrop_to('backdrop1')
        assert ex.opcode == 'looks_switchbackdropto'

    def test_costume_number_name_default(self) -> None:
        ex = looks.costume_number_name()
        assert ex.opcode == 'looks_costumenumbername'
        # Default field value should be 'number'
        assert 'NUMBER_NAME' in ex.fields
        assert ex.fields['NUMBER_NAME'].value == 'number'

    def test_costume_number_name_with_arg(self) -> None:
        ex = looks.costume_number_name('name')
        assert ex.opcode == 'looks_costumenumbername'
        assert ex.fields['NUMBER_NAME'].value == 'name'

    def test_backdrop_number_name(self) -> None:
        ex = looks.backdrop_number_name('number')
        assert ex.opcode == 'looks_backdropnumbername'
        assert ex.fields['NUMBER_NAME'].value == 'number'

    def test_set_effect(self) -> None:
        ex = looks.set_effect('GHOST', 50)
        assert ex.opcode == 'looks_seteffectto'

    def test_change_effect(self) -> None:
        ex = looks.change_effect('GHOST', 10)
        assert ex.opcode == 'looks_changeeffectby'

    def test_clear_effects(self) -> None:
        assert looks.clear_effects().opcode == 'looks_cleargraphiceffects'

    def test_set_size(self) -> None:
        ex = looks.set_size_to(200)
        assert ex.opcode == 'looks_setsizeto'

    def test_change_size(self) -> None:
        ex = looks.change_size_by(10)
        assert ex.opcode == 'looks_changesizeby'

    def test_size_reporter(self) -> None:
        assert looks.size().opcode == 'looks_size'

    def test_go_to_front_back(self) -> None:
        ex = looks.go_to_front_back('front')
        assert ex.opcode == 'looks_gotofrontback'
        assert ex.fields['FRONT_BACK'].value == 'front'


class TestCategoryEvents:
    """events.* blocks."""

    def test_broadcast(self) -> None:
        ex = events.broadcast('done')
        assert ex.opcode == 'event_broadcast'

    def test_broadcast_and_wait(self) -> None:
        ex = events.broadcast_and_wait('done')
        assert ex.opcode == 'event_broadcastandwait'

    def test_when_backdrop_switches_to(self) -> None:
        ex = events.when_backdrop_switches_to('backdrop1')
        assert ex.opcode == 'event_whenbackdropswitchesto'

    def test_when_greater_than(self) -> None:
        ex = events.when_greater_than(metric='loudness', value=10)
        assert ex.opcode == 'event_whengreaterthan'
        assert ex.fields['WHENGREATERTHAN_MENU'].value == 'loudness'


class TestCategoryDataExtended:
    """data.* blocks beyond the basics."""

    def test_change_variable(self) -> None:
        ex = data.change_variable('score', 1)
        assert ex.opcode == 'data_changevariableby'

    def test_show_variable(self) -> None:
        ex = data.show_variable('score')
        assert ex.opcode == 'data_showvariable'

    def test_hide_variable(self) -> None:
        ex = data.hide_variable('score')
        assert ex.opcode == 'data_hidevariable'

    def test_delete_of_list(self) -> None:
        ex = data.delete_of_list('items', 1)
        assert ex.opcode == 'data_deleteoflist'

    def test_delete_all_of_list(self) -> None:
        ex = data.delete_all_of_list('items')
        assert ex.opcode == 'data_deletealloflist'

    def test_insert_at_list(self) -> None:
        ex = data.insert_at_list('items', 1, data.variable('x'))
        assert ex.opcode == 'data_insertatlist'

    def test_replace_item_of_list(self) -> None:
        ex = data.replace_item_of_list('items', 1, 'y')
        assert ex.opcode == 'data_replaceitemoflist'

    def test_item_of_list(self) -> None:
        ex = data.item_of_list('items', 1)
        assert ex.opcode == 'data_itemoflist'

    def test_length_of_list(self) -> None:
        ex = data.length_of_list('items')
        assert ex.opcode == 'data_lengthoflist'

    def test_list_contains_item(self) -> None:
        ex = data.list_contains_item('items', 'x')
        assert ex.opcode == 'data_listcontainsitem'


class TestCategorySensingExtended:
    """sensing.* blocks beyond the basics."""

    def test_ask_and_wait(self) -> None:
        ex = sensing.ask_and_wait('what?')
        assert ex.opcode == 'sensing_askandwait'

    def test_key_pressed(self) -> None:
        ex = sensing.key_pressed('space')
        assert ex.opcode == 'sensing_keypressed'
        assert ex.fields['KEY_OPTION'].value == 'space'

    def test_mouse_x(self) -> None:
        assert sensing.mouse_x().opcode == 'sensing_mousex'

    def test_mouse_y(self) -> None:
        assert sensing.mouse_y().opcode == 'sensing_mousey'

    def test_mouse_down(self) -> None:
        assert sensing.mouse_down().opcode == 'sensing_mousedown'

    def test_timer(self) -> None:
        assert sensing.timer().opcode == 'sensing_timer'

    def test_reset_timer(self) -> None:
        assert sensing.reset_timer().opcode == 'sensing_resettimer'

    def test_current(self) -> None:
        ex = sensing.current('year')
        assert ex.opcode == 'sensing_current'
        assert ex.fields['CURRENTMENU'].value == 'year'

    def test_days_since_2000(self) -> None:
        assert sensing.days_since_2000().opcode == 'sensing_dayssince2000'

    def test_username(self) -> None:
        assert sensing.username().opcode == 'sensing_username'

    def test_answer(self) -> None:
        assert sensing.answer().opcode == 'sensing_answer'


class TestCategoryControlExtended:
    """control.* blocks beyond basics."""

    def test_stop_all(self) -> None:
        ex = control.stop('all')
        assert ex.opcode == 'control_stop'
        assert ex.fields['STOP_OPTION'].value == 'all'

    def test_stop_this_script(self) -> None:
        ex = control.stop('this script')
        assert ex.fields['STOP_OPTION'].value == 'this script'

    def test_create_clone_of(self) -> None:
        ex = control.create_clone_of('_myself_')
        assert ex.opcode == 'control_create_clone_of'

    def test_delete_this_clone(self) -> None:
        assert control.delete_this_clone().opcode == 'control_delete_this_clone'

    def test_wait(self) -> None:
        ex = control.wait(0.5)
        assert ex.opcode == 'control_wait'

    def test_wait_until(self) -> None:
        ex = control.wait_until(operators.eq(1, 1))
        assert ex.opcode == 'control_wait_until'


class TestCategorySound:
    """sound.* blocks."""

    def test_play(self) -> None:
        ex = sound.play('meow')
        assert ex.opcode == 'sound_play'

    def test_play_until_done(self) -> None:
        ex = sound.play_until_done('meow')
        assert ex.opcode == 'sound_playuntildone'

    def test_stop_all_sounds(self) -> None:
        assert sound.stop_all_sounds().opcode == 'sound_stopallsounds'

    def test_set_volume(self) -> None:
        ex = sound.set_volume_to(50)
        assert ex.opcode == 'sound_setvolumeto'

    def test_change_volume(self) -> None:
        ex = sound.change_volume_by(10)
        assert ex.opcode == 'sound_changevolumeby'

    def test_volume(self) -> None:
        assert sound.volume().opcode == 'sound_volume'


class TestCategoryOperatorsExtended:
    """operators.* blocks beyond basics."""

    def test_mathop_ceiling(self) -> None:
        ex = operators._mathop('ceiling', 3.5)
        assert ex.opcode == 'operator_mathop'
        assert ex.fields['OPERATOR'].value == 'ceiling'
        assert ex.inputs['NUM'].value == 3.5

    def test_mathop_floor(self) -> None:
        ex = operators.floor_(3.5)
        assert ex.opcode == 'operator_mathop'
        assert ex.fields['OPERATOR'].value == 'floor'

    def test_mathop_abs(self) -> None:
        ex = operators.abs_(-5)
        assert ex.opcode == 'operator_mathop'
        assert ex.fields['OPERATOR'].value == 'abs'

    def test_mathop_sin(self) -> None:
        ex = operators.sin(90)
        assert ex.opcode == 'operator_mathop'

    def test_subtract(self) -> None:
        ex = operators.sub(10, 3)
        assert ex.opcode == 'operator_subtract'

    def test_multiply(self) -> None:
        ex = operators.mult(4, 5)
        assert ex.opcode == 'operator_multiply'

    def test_divide(self) -> None:
        ex = operators.div(10, 2)
        assert ex.opcode == 'operator_divide'

    def test_random(self) -> None:
        ex = operators.random(1, 10)
        assert ex.opcode == 'operator_random'
        assert ex.inputs['FROM'].value == 1
        assert ex.inputs['TO'].value == 10

    def test_join(self) -> None:
        ex = operators.join('a', 'b')
        assert ex.opcode == 'operator_join'

    def test_letter_of(self) -> None:
        ex = operators.letter_of(1, 'hello')
        assert ex.opcode == 'operator_letter_of'

    def test_length(self) -> None:
        ex = operators.length('hello')
        assert ex.opcode == 'operator_length'

    def test_contains(self) -> None:
        ex = operators.contains('hello', 'el')
        assert ex.opcode == 'operator_contains'

    def test_mod(self) -> None:
        ex = operators.mod(10, 3)
        assert ex.opcode == 'operator_mod'

    def test_round(self) -> None:
        ex = operators.round_(3.7)
        assert ex.opcode == 'operator_round'

    def test_lt(self) -> None:
        ex = operators.lt(1, 2)
        assert ex.opcode == 'operator_lt'

    def test_gt(self) -> None:
        ex = operators.gt(3, 2)
        assert ex.opcode == 'operator_gt'

    def test_eq(self) -> None:
        ex = operators.eq(1, 1)
        assert ex.opcode == 'operator_equals'


class TestVariableInlining:
    """data.variable() is inlined as OBSOLETE_FLAG when used as an input."""

    def test_variable_inlined_in_control_wait(self) -> None:
        """control.wait(data.variable('x')) inlines the variable."""
        ex = control.wait(data.variable('x'))
        assert ex.opcode == 'control_wait'
        dur = ex.inputs['DURATION']
        assert dur.variable_name == 'x'
        assert dur.value is None  # not a block reference

    def test_variable_inlined_in_sensing_touching(self) -> None:
        """sensing.touching(data.variable('x')) inlines the variable."""
        ex = sensing.touching(data.variable('x'))
        assert ex.opcode == 'sensing_touchingobject'
        inp = ex.inputs['TOUCHINGOBJECTMENU']
        assert inp.variable_name == 'x'

    def test_variable_not_inlined_when_standalone(self) -> None:
        """data.variable('x') alone (not as input) is still a Reporter block."""
        ex = data.variable('x')
        assert ex.opcode == 'data_variable'
        assert ex.fields['VARIABLE'].value == 'x'

    def test_literal_not_inlined(self) -> None:
        """Literal values use shadow flag, not variable_name."""
        ex = control.wait(0.5)
        dur = ex.inputs['DURATION']
        assert dur.variable_name is None

    def test_reporter_not_inlined(self) -> None:
        """Non-variable reporters (e.g. operators.add) use block ref."""
        ex = control.wait(operators.add(data.variable('x'), 1))
        dur = ex.inputs['DURATION']
        assert dur.variable_name is None  # not a variable, it's a block ref
        assert dur.value is not None  # block ID reference
