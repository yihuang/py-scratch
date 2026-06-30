"""Unit tests — scheduler, thread lifecycle, and every opcode category."""

from __future__ import annotations

from itertools import count
from typing import Any

from scratch.vm import ListVar, Runtime, Target, Variable, make_block
from scratch.vm.opcodes import OPCODE_MAP
from scratch.vm.types import Block

# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════

_id_counter = count(1)


def _id() -> str:
    return f'b{next(_id_counter)}'


def _stack(*opcodes: str) -> Target:
    t = _make_tgt()
    prev = None
    head_id = None
    for i, op in enumerate(opcodes):
        bid = f'b{i}'
        t.blocks[bid] = Block(id=bid, opcode=op, next=None, parent=prev)
        if prev is not None:
            t.blocks[prev].next = bid
        if head_id is None:
            head_id = bid
        prev = bid
    if head_id is not None:
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = head_id
    t._rebuild_hat_cache()
    return t


def _make_tgt(name: str = 'Sprite', add_hat: bool = True) -> Target:
    t = Target(name=name, is_stage=False)
    if add_hat:
        hid = f'h{next(_id_counter)}'
        t.blocks[hid] = make_block('event_whenflagclicked', hid, top_level=True, next_=None)
    return t


def _set(
    target: Target,
    block_id: str,
    inputs: dict[str, Any] | None = None,
    fields: dict[str, Any] | None = None,
) -> None:
    """Set inputs/fields on a block created by ``_stack`` in place."""
    block = target.blocks[block_id]
    if inputs:
        block.inputs = inputs
    if fields:
        block.fields = fields


def _op(
    opcode: str, inputs: dict[str, Any] | None = None, fields: dict[str, Any] | None = None
) -> Block:
    """Create a single block with no next/parent."""
    return Block(id=_id(), opcode=opcode, inputs=inputs or {}, fields=fields or {})


def _rt(main: Target | list[Target]) -> Runtime:
    """Build a Runtime with a stage and one or more sprites, register opcodes."""
    rt = Runtime()
    rt._real_time = False  # deterministic tick-based mode for tests
    rt.add_target(Target(name='Stage', is_stage=True))
    if isinstance(main, list):
        for t in main:
            rt.add_target(t)
    else:
        rt.add_target(main)
    rt.register_all(OPCODE_MAP)
    return rt


def _run(target: Target, *, steps: int = 20) -> Runtime:
    """Green flag the target's Runtime and step ``steps`` frames."""
    rt = _rt(target)
    rt.green_flag()
    for _ in range(steps):
        rt.step()
    return rt


# ═══════════════════════════════════════════════════════════════════════
#  Scheduler & Thread Lifecycle
# ═══════════════════════════════════════════════════════════════════════


class TestScheduler:
    def test_finite_script_cleans_up(self) -> None:
        """A non-looping script finishes and is removed from the thread list."""
        t = _stack('motion_movesteps')
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_forever_stays_alive(self) -> None:
        """A forever loop keeps the thread alive."""
        t = _make_tgt()
        t.blocks['f'] = make_block('control_forever', 'f', inputs={'SUBSTACK': 'b0'})
        t.blocks['b0'] = Block(id='b0', opcode='motion_movesteps')
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'f'
        t._rebuild_hat_cache()
        rt = _run(t, steps=50)
        assert len(rt.threads) == 1
        assert not rt.threads[0].is_done()

    def test_green_flag_resets(self) -> None:
        """Green flag stops old threads before starting new ones."""
        t = _make_tgt()
        t.blocks['f'] = make_block('control_forever', 'f', inputs={'SUBSTACK': 'b0'})
        t.blocks['b0'] = Block(id='b0', opcode='motion_movesteps')
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'f'
        t._rebuild_hat_cache()
        rt = _rt(t)
        for _ in range(3):
            rt.green_flag()
            assert len(rt.threads) == 1
            for _ in range(5):
                rt.step()
            assert len(rt.threads) == 1

    def test_empty_hat_does_not_crash(self) -> None:
        """A hat block with no ``next`` creates a thread that immediately finishes."""
        t = Target(name='T', is_stage=False)
        t.blocks['h'] = make_block('event_whenflagclicked', 'h', top_level=True)
        t._rebuild_hat_cache()
        rt = _run(t)
        assert len(rt.threads) == 0


# ═══════════════════════════════════════════════════════════════════════
#  Wait / Timing (deterministic)
# ═══════════════════════════════════════════════════════════════════════


class TestWait:
    def test_wait_zero_is_instant(self) -> None:
        t = _stack('control_wait')
        t.blocks['b0'] = _op('control_wait', inputs={'DURATION': 0})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_wait_one_frame(self) -> None:
        t = _stack('control_wait')
        _set(t, 'b0', inputs={'DURATION': 0.01})
        rt = _rt(t)
        rt.green_flag()
        rt.step()  # enters WAITING (queued at tick ceil(0.01*60)=1)
        assert rt.threads[0].status == 'waiting'
        rt.step()  # tick 1 >= 1 → wake → done
        assert len(rt.threads) == 0

    def test_two_waits_in_sequence(self) -> None:
        t = _stack('control_wait', 'control_wait')
        _set(t, 'b0', inputs={'DURATION': 0.1})  # 6 frames
        _set(t, 'b1', inputs={'DURATION': 0.2})  # 12 frames
        rt = _rt(t)
        rt.green_flag()
        for _ in range(6):
            rt.step()  # steps 0-5, b0 WAITING at 6
        rt.step()  # step 6 → b0 wake → b1 WAITING at 19 (7+12)
        for _ in range(12):
            rt.step()  # steps 7-18, b1 WAITING
        assert len(rt.threads) == 1
        rt.step()  # step 19 → b1 wake → done
        assert len(rt.threads) == 0

    def test_wait_until_polls(self) -> None:
        t = _stack('control_wait_until')
        _set(t, 'b0', inputs={'CONDITION': False})
        rt = _rt(t)
        rt.green_flag()
        rt.step()
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 1


# ═══════════════════════════════════════════════════════════════════════
#  Control
# ═══════════════════════════════════════════════════════════════════════


class TestControl:
    def test_repeat_loop(self) -> None:
        t = _make_tgt()
        t.blocks['r'] = make_block('control_repeat', 'r', inputs={'TIMES': 3, 'SUBSTACK': 'b0'})
        t.blocks['b0'] = Block(id='b0', opcode='motion_movesteps', inputs={'STEPS': 5})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'r'
        t._rebuild_hat_cache()
        rt = _run(t, steps=30)
        assert len(rt.threads) == 0
        assert t.x == 15.0  # 3 × 5 steps, direction 90 → +x

    def test_repeat_zero_times(self) -> None:
        t = _make_tgt()
        t.blocks['r'] = make_block('control_repeat', 'r', inputs={'TIMES': 0, 'SUBSTACK': 'b0'})
        t.blocks['b0'] = Block(id='b0', opcode='motion_movesteps', inputs={'STEPS': 10})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'r'
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.y == 0.0

    def test_forever_with_yield(self) -> None:
        t = _make_tgt()
        t.blocks['f'] = make_block('control_forever', 'f', inputs={'SUBSTACK': 'b0'})
        t.blocks['b0'] = Block(id='b0', opcode='motion_movesteps', inputs={'STEPS': 1})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'f'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        assert len(rt.threads) == 1
        assert t.x > 0

    def test_if_true(self) -> None:
        t = _stack('control_if')
        _set(t, 'b0', inputs={'CONDITION': True, 'SUBSTACK': 'b1'})
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': 10}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 10.0

    def test_if_false(self) -> None:
        t = _stack('control_if')
        _set(t, 'b0', inputs={'CONDITION': False, 'SUBSTACK': 'b1'})
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': 10}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.y == 0.0

    def test_if_else_true_branch(self) -> None:
        t = _stack('control_if_else')
        t.blocks['b0'] = _op(
            'control_if_else', inputs={'CONDITION': True, 'SUBSTACK': 'b1', 'SUBSTACK2': 'b2'}
        )
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': 10}, parent='b0'
        )
        t.blocks['b2'] = Block(
            id='b2', opcode='motion_turnright', inputs={'DEGREES': 90}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 10.0

    def test_if_else_false_branch(self) -> None:
        t = _stack('control_if_else')
        t.blocks['b0'] = _op(
            'control_if_else', inputs={'CONDITION': False, 'SUBSTACK': 'b1', 'SUBSTACK2': 'b2'}
        )
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': 10}, parent='b0'
        )
        t.blocks['b2'] = Block(id='b2', opcode='motion_movesteps', inputs={'STEPS': 5}, parent='b0')
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 5.0

    def test_repeat_until_true(self) -> None:
        t = _stack('control_repeat_until')
        t.blocks['b0'] = _op('control_repeat_until', inputs={'CONDITION': True, 'SUBSTACK': 'b1'})
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': 10}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.y == 0.0


# ═══════════════════════════════════════════════════════════════════════
#  Event
# ═══════════════════════════════════════════════════════════════════════


class TestEvent:
    def test_broadcast_starts_hat(self) -> None:
        t1 = Target(name='A', is_stage=False)
        t1.blocks['h'] = make_block('event_whenflagclicked', 'h', top_level=True, next_='b')
        t1.blocks['b'] = make_block('event_broadcast', 'b', fields={'BROADCAST_INPUT': 'msg'})
        t1._rebuild_hat_cache()

        t2 = Target(name='B', is_stage=False)
        t2.blocks['h2'] = make_block(
            'event_whenbroadcastreceived',
            'h2',
            top_level=True,
            fields={'BROADCAST_OPTION': 'msg'},
            next_='m',
        )
        t2.blocks['m'] = Block(id='m', opcode='motion_movesteps', inputs={'STEPS': 5})
        t2._rebuild_hat_cache()

        rt = _rt([t1, t2])
        rt.green_flag()
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 0
        assert t2.x == 5.0


# ═══════════════════════════════════════════════════════════════════════
#  Motion
# ═══════════════════════════════════════════════════════════════════════


class TestMotion:
    def test_movesteps(self) -> None:
        t = _stack('motion_movesteps')
        _set(t, 'b0', inputs={'STEPS': 10})
        rt = _run(t)
        assert len(rt.threads) == 0
        assert t.x == 10.0  # direction 90 = positive x

    def test_gotoxy(self) -> None:
        t = _stack('motion_gotoxy')
        _set(t, 'b0', inputs={'X': -100, 'Y': 200})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.x == -100
        assert t.y == 200

    def test_gox_goy(self) -> None:
        t = _stack('motion_gox', 'motion_goy')
        _set(t, 'b0', inputs={'X': 50})
        _set(t, 'b1', inputs={'Y': -30})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.x == 50
        assert t.y == -30

    def test_turn(self) -> None:
        t = _stack('motion_turnright', 'motion_turnleft')
        _set(t, 'b0', inputs={'DEGREES': 45})
        _set(t, 'b1', inputs={'DEGREES': 90})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.direction == 135  # 90 - 45 + 90 = 135

    def test_change_xy(self) -> None:
        t = _stack('motion_changexby', 'motion_changeyby')
        _set(t, 'b0', inputs={'DX': 15})
        _set(t, 'b1', inputs={'DY': -25})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.x == 15
        assert t.y == -25

    def test_set_direction(self) -> None:
        t = _stack('motion_setdirection')
        _set(t, 'b0', inputs={'DIRECTION': 180})
        rt = _run(t)
        assert t.direction == 180

    def test_xposition(self) -> None:
        t = _stack('motion_gotoxy', 'motion_xposition')
        _set(t, 'b0', inputs={'X': 42, 'Y': 0})
        rt = _run(t)
        assert t.x == 42

    def test_glide_smoke(self) -> None:
        t = _stack('motion_glideto')
        _set(t, 'b0', inputs={'SECS': 0.1, 'X': 100, 'Y': 0})
        rt = _rt(t)
        rt.green_flag()
        for _ in range(30):
            rt.step()
        assert abs(t.x - 100) < 0.1


# ═══════════════════════════════════════════════════════════════════════
#  Looks
# ═══════════════════════════════════════════════════════════════════════


class TestLooks:
    def test_show_hide(self) -> None:
        t = _stack('looks_hide', 'looks_show')
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.visible is True

    def test_goto_front(self) -> None:
        t = _make_tgt()
        t.blocks['b0'] = _op('looks_gotofrontback', fields={'FRONT_BACK': 'front'})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t.layer_order = 0
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        assert t.layer_order >= 1

    def test_size(self) -> None:
        t = _stack('looks_setsizeto', 'looks_changesizeby')
        _set(t, 'b0', inputs={'SIZE': 150})
        _set(t, 'b1', inputs={'CHANGE': -30})
        rt = _run(t)
        assert t.size == 120


# ═══════════════════════════════════════════════════════════════════════
#  Operators
# ═══════════════════════════════════════════════════════════════════════


class TestOperators:
    def test_add(self) -> None:
        t = _stack('operator_add')
        _set(t, 'b0', inputs={'NUM1': 3, 'NUM2': 4})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_subtract(self) -> None:
        t = _stack('operator_subtract')
        _set(t, 'b0', inputs={'NUM1': 10, 'NUM2': 3})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_random(self) -> None:
        t = _stack('operator_random')
        _set(t, 'b0', inputs={'FROM': 1, 'TO': 6})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_join(self) -> None:
        t = _stack('operator_join')
        _set(t, 'b0', inputs={'STRING1': 'hello', 'STRING2': 'world'})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_equals(self) -> None:
        t = _stack('operator_equals')
        _set(t, 'b0', inputs={'OPERAND1': 5, 'OPERAND2': 5})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_mathop_sin(self) -> None:
        t = _stack('operator_mathop')
        t.blocks['b0'] = _op('operator_mathop', inputs={'NUM': 90}, fields={'OPERATOR': 'sin'})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert len(rt.threads) == 0


# ═══════════════════════════════════════════════════════════════════════
#  Data — Variables
# ═══════════════════════════════════════════════════════════════════════


class TestDataVariables:
    def test_set_variable(self) -> None:
        t = _stack('data_setvariableto')
        _set(t, 'b0', inputs={'VALUE': 42}, fields={'VARIABLE': 'score'})
        t.variables['score'] = Variable('score', 0)
        rt = _run(t)
        v = t.lookup_variable('score')
        assert v is not None and v.value == 42

    def test_change_variable(self) -> None:
        t = _stack('data_changevariableby')
        _set(t, 'b0', inputs={'VALUE': 10}, fields={'VARIABLE': 'score'})
        t.variables['score'] = Variable('score', 5)
        rt = _run(t)
        v = t.lookup_variable('score')
        assert v is not None and v.value == 15

    def test_stage_variable_fallback(self) -> None:
        """Setting a sprite variable with no match falls back to stage."""
        t = _stack('data_setvariableto')
        t.blocks['b0'] = _op(
            'data_setvariableto', inputs={'VALUE': 99}, fields={'VARIABLE': 'global_x'}
        )
        t.variables.pop('global_x', None)
        t._rebuild_hat_cache()
        stage = Target(name='Stage', is_stage=True)
        stage.variables['global_x'] = Variable('global_x', 0)
        rt = Runtime()
        rt.add_target(stage)
        rt.add_target(t)
        rt.register_all(OPCODE_MAP)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        v = stage.lookup_variable('global_x')
        assert v is not None and v.value == 99


# ═══════════════════════════════════════════════════════════════════════
#  Data — Lists
# ═══════════════════════════════════════════════════════════════════════


class TestDataLists:
    def test_add_to_list(self) -> None:
        t = _stack('data_addtolist')
        _set(t, 'b0', inputs={'ITEM': 'x'}, fields={'LIST': 'items'})
        t.lists['items'] = ListVar('items')
        rt = _run(t)
        assert t.lists['items'].contents == ['x']

    def test_add_delete_list(self) -> None:
        t = _stack('data_addtolist', 'data_deleteoflist')
        _set(t, 'b0', inputs={'ITEM': 'a'}, fields={'LIST': 'items'})
        _set(t, 'b1', inputs={'INDEX': 1}, fields={'LIST': 'items'})
        t.lists['items'] = ListVar('items')
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.lists['items'].contents == []


# ═══════════════════════════════════════════════════════════════════════
#  Sensing
# ═══════════════════════════════════════════════════════════════════════


class TestSensing:
    def test_timer(self) -> None:
        t = _stack('sensing_resettimer', 'sensing_timer')
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_keypressed(self) -> None:
        t = _stack('sensing_keypressed')
        _set(t, 'b0', fields={'KEY_OPTION': 'space'})
        rt = _run(t)
        assert len(rt.threads) == 0


# ═══════════════════════════════════════════════════════════════════════
#  Pen
# ═══════════════════════════════════════════════════════════════════════


class TestPen:
    def test_pen_down_up(self) -> None:
        t = _stack('pen_penDown', 'pen_penUp')
        rt = _run(t)
        assert t.pen_down is False

    def test_pen_down_and_move(self) -> None:
        t = _stack('pen_penDown', 'motion_movesteps')
        _set(t, 'b1', inputs={'STEPS': 10})
        rt = _run(t)
        assert t.pen_down is True
        assert t.x == 10.0


# ═══════════════════════════════════════════════════════════════════════
#  Integration: mixed opcodes
# ═══════════════════════════════════════════════════════════════════════


class TestMixed:
    def test_move_then_wait_then_move(self) -> None:
        """Verifies a real Scratch-like script: move → wait 0.1s → move."""
        t = _stack('motion_movesteps', 'control_wait', 'motion_movesteps')
        _set(t, 'b0', inputs={'STEPS': 20})
        _set(t, 'b1', inputs={'DURATION': 0.1})  # 6 frames
        _set(t, 'b2', inputs={'STEPS': 10})
        t.y = 0.0
        rt = _rt(t)
        rt.green_flag()
        rt.step()  # b0 runs → x=20, advances to b1
        assert t.x == 20.0
        # b1 runs: control_wait enters WAITING at tick ceil(0.1*60)=6
        # b1 runs: control_wait enters WAITING at tick 1 + ceil(0.1*60) = 7
        rt.step()
        assert t.x == 20.0
        assert rt.threads[0].status == 'waiting'
        for _ in range(5):
            rt.step()
            assert rt.threads[0].status == 'waiting'
        rt.step()  # tick 7 → wake → resume b1 → StopIteration → advance to b2
        assert t.x == 20.0  # b2 hasn't run yet; _step_thread only advances
        rt.step()  # b2 runs (instant) → done
        assert t.x == 30.0
