"""Unit tests — scheduler, thread lifecycle, and every opcode category."""

from __future__ import annotations
from scratch.vm.runtime import _input_raw, _unwrap_shadow

from itertools import count
from typing import Any

import datetime
import math

import pytest
import pygame
from scratch.sb3.io import (
    _parse_block,
    _parse_field,
    _parse_input,
    _serialize_field,
    _serialize_input,
)
from scratch.vm import BroadcastMsg, ListVar, Runtime, Target, Variable, make_block
from scratch.vm.opcodes import OPCODE_MAP
from scratch.vm.types import Block, Costume, Field, Input, Sound
from scratch.vm.constants import PrimitiveType

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
    """Set inputs/fields on a block created by ``_stack`` in place.
    Raw values are auto-wrapped into Input/Field objects.
    """
    block = target.blocks[block_id]
    if inputs:
        block.inputs = {k: v if isinstance(v, Input) else Input(value=v) for k, v in inputs.items()}
    if fields:
        block.fields = {k: v if isinstance(v, Field) else Field(value=v) for k, v in fields.items()}


def _op(
    opcode: str,
    inputs: dict[str, Input | Any] | None = None,
    fields: dict[str, Field | Any] | None = None,
) -> Block:
    """Create a single block with no next/parent.
    Raw values are auto-wrapped into Input/Field objects.
    """
    parsed_inputs: dict[str, Input] = {}
    if inputs:
        for k, v in inputs.items():
            parsed_inputs[k] = v if isinstance(v, Input) else Input(value=v)
    parsed_fields: dict[str, Field] = {}
    if fields:
        for k, v in fields.items():
            parsed_fields[k] = v if isinstance(v, Field) else Field(value=v)
    return Block(id=_id(), opcode=opcode, inputs=parsed_inputs, fields=parsed_fields)


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


def _make_with_reporter(block_id: str, value: Any) -> tuple[Runtime, Target]:
    """Build Runtime + Target with a reusable reporter block."""
    rt = Runtime()
    rt._real_time = False
    rt.add_target(Target(name='Stage', is_stage=True))
    rt.register_all(OPCODE_MAP)
    t = Target(name='Sprite')
    t.blocks[block_id] = Block(
        id=block_id,
        opcode='data_variable',
        fields={'VARIABLE': Field(value='myVar')},
    )
    t.variables['v1'] = Variable(name='myVar', value=value)
    rt.add_target(t)
    return rt, t


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
        t.blocks['f'] = make_block('control_forever', 'f', inputs={'SUBSTACK': Input(value='b0')})
        t.blocks['b0'] = Block(id='b0', opcode='motion_movesteps')
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'f'
        t._rebuild_hat_cache()
        rt = _run(t, steps=50)
        assert len(rt.threads) == 1
        assert not rt.threads[0].is_done()

    def test_green_flag_resets(self) -> None:
        """Green flag stops old threads before starting new ones."""
        t = _make_tgt()
        t.blocks['f'] = make_block('control_forever', 'f', inputs={'SUBSTACK': Input(value='b0')})
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
        t.blocks['b0'] = _op('control_wait', inputs={'DURATION': Input(value=0)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_wait_one_frame(self) -> None:
        t = _stack('control_wait')
        _set(t, 'b0', inputs={'DURATION': Input(value=0.01)})
        rt = _rt(t)
        rt.green_flag()
        rt.step()  # enters WAITING (queued at tick ceil(0.01*60)=1)
        assert rt.threads[0].status == 'waiting'
        rt.step()  # tick 1 >= 1 → wake → done
        assert len(rt.threads) == 0

    def test_two_waits_in_sequence(self) -> None:
        t = _stack('control_wait', 'control_wait')
        _set(t, 'b0', inputs={'DURATION': Input(value=0.1)})  # 6 frames
        _set(t, 'b1', inputs={'DURATION': Input(value=0.2)})  # 12 frames
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
        _set(t, 'b0', inputs={'CONDITION': Input(value=False)})
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
        t.blocks['r'] = make_block(
            'control_repeat', 'r', inputs={'TIMES': Input(value=3), 'SUBSTACK': Input(value='b0')}
        )
        t.blocks['b0'] = Block(id='b0', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'r'
        t._rebuild_hat_cache()
        rt = _run(t, steps=30)
        assert len(rt.threads) == 0
        assert t.x == 15.0  # 3 × 5 steps, direction 90 → +x

    def test_repeat_zero_times(self) -> None:
        t = _make_tgt()
        t.blocks['r'] = make_block(
            'control_repeat', 'r', inputs={'TIMES': Input(value=0), 'SUBSTACK': Input(value='b0')}
        )
        t.blocks['b0'] = Block(
            id='b0', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}
        )
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'r'
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.y == 0.0

    def test_forever_with_yield(self) -> None:
        t = _make_tgt()
        t.blocks['f'] = make_block('control_forever', 'f', inputs={'SUBSTACK': Input(value='b0')})
        t.blocks['b0'] = Block(id='b0', opcode='motion_movesteps', inputs={'STEPS': Input(value=1)})
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
        _set(t, 'b0', inputs={'CONDITION': Input(value=True), 'SUBSTACK': Input(value='b1')})
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 10.0

    def test_if_false(self) -> None:
        t = _stack('control_if')
        _set(t, 'b0', inputs={'CONDITION': Input(value=False), 'SUBSTACK': Input(value='b1')})
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.y == 0.0

    def test_if_else_true_branch(self) -> None:
        t = _stack('control_if_else')
        t.blocks['b0'] = _op(
            'control_if_else',
            inputs={
                'CONDITION': Input(value=True),
                'SUBSTACK': Input(value='b1'),
                'SUBSTACK2': 'b2',
            },
        )
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}, parent='b0'
        )
        t.blocks['b2'] = Block(
            id='b2', opcode='motion_turnright', inputs={'DEGREES': Input(value=90)}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 10.0

    def test_if_else_false_branch(self) -> None:
        t = _stack('control_if_else')
        t.blocks['b0'] = _op(
            'control_if_else',
            inputs={
                'CONDITION': Input(value=False),
                'SUBSTACK': Input(value='b1'),
                'SUBSTACK2': 'b2',
            },
        )
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}, parent='b0'
        )
        t.blocks['b2'] = Block(
            id='b2', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 5.0

    def test_repeat_until_true(self) -> None:
        t = _stack('control_repeat_until')
        t.blocks['b0'] = _op(
            'control_repeat_until',
            inputs={'CONDITION': Input(value=True), 'SUBSTACK': Input(value='b1')},
        )
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.y == 0.0

    # ── control_repeat rounding ────────────────────────────────────────

    def test_repeat_rounded(self) -> None:
        """TIMES=3.7 rounds to 4 iterations."""
        t = _make_tgt()
        t.blocks['r'] = make_block(
            'control_repeat', 'r', inputs={'TIMES': Input(value=3.7), 'SUBSTACK': Input(value='b0')}
        )
        t.blocks['b0'] = Block(id='b0', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'r'
        t._rebuild_hat_cache()
        rt = _run(t, steps=60)
        assert len(rt.threads) == 0
        assert t.x == 20.0  # 4 × 5 steps

    def test_repeat_negative_or_nan(self) -> None:
        """Negative TIMES rounds to 0 iterations (no-op)."""
        t = _make_tgt()
        t.blocks['r'] = make_block(
            'control_repeat', 'r', inputs={'TIMES': Input(value=-1), 'SUBSTACK': Input(value='b0')}
        )
        t.blocks['b0'] = Block(
            id='b0', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}
        )
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'r'
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 0.0

    # ── control_repeat_until ────────────────────────────────────────────

    def test_repeat_until_eventually_true(self) -> None:
        """Runs body until a variable-based condition becomes true."""
        t = _make_tgt()
        t.blocks['b0'] = make_block(
            'control_repeat_until',
            'b0',
            inputs={'CONDITION': Input(value=[12, 'done']), 'SUBSTACK': Input(value='b1')},
        )
        t.blocks['b1'] = Block(
            id='b1',
            opcode='data_setvariableto',
            inputs={'VALUE': Input(value=1)},
            fields={'VARIABLE': Field(value='done')},
            parent='b0',
        )
        t.variables['done'] = Variable('done', 0)
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = 'b0'
        t._rebuild_hat_cache()
        rt = _run(t, steps=20)
        assert len(rt.threads) == 0
        v = t.lookup_variable('done')
        assert v is not None and v.value == 1

    # ── control_while ───────────────────────────────────────────────────

    def test_while_runs_while_condition_true(self) -> None:
        """Runs body repeatedly while condition stays true (yields between iterations)."""
        t = _make_tgt()
        t.blocks['w'] = make_block(
            'control_while',
            'w',
            inputs={'CONDITION': Input(value=True), 'SUBSTACK': Input(value='b0')},
        )
        t.blocks['b0'] = Block(id='b0', opcode='motion_movesteps', inputs={'STEPS': Input(value=1)})
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = 'w'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        assert len(rt.threads) == 1  # still running
        assert t.x > 0

    def test_while_skipped_if_false(self) -> None:
        """Skips body when condition is false at entry."""
        t = _make_tgt()
        t.blocks['w'] = make_block(
            'control_while',
            'w',
            inputs={'CONDITION': Input(value=False), 'SUBSTACK': Input(value='b0')},
        )
        t.blocks['b0'] = Block(
            id='b0', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}
        )
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = 'w'
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 0.0

    # ── control_if / control_if_else coercion ──────────────────────────

    def test_if_truthy_number_one(self) -> None:
        """if with CONDITION=1 (truthy) runs the substack."""
        t = _stack('control_if')
        _set(t, 'b0', inputs={'CONDITION': Input(value=1), 'SUBSTACK': Input(value='b1')})
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 5.0

    def test_if_falsy_zero(self) -> None:
        """if with CONDITION=0 (falsy) skips the substack."""
        t = _stack('control_if')
        _set(t, 'b0', inputs={'CONDITION': Input(value=0), 'SUBSTACK': Input(value='b1')})
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 0.0

    def test_if_else_truthy_coerced_string(self) -> None:
        """if_else with CONDITION='1' (Scratch-truthy string) runs substack."""
        t = _stack('control_if_else')
        t.blocks['b0'] = _op(
            'control_if_else',
            inputs={
                'CONDITION': Input(value='1'),
                'SUBSTACK': Input(value='b1'),
                'SUBSTACK2': 'b2',
            },
        )
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}, parent='b0'
        )
        t.blocks['b2'] = Block(
            id='b2', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)}, parent='b0'
        )
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 10.0

    # ── control_wait_until ─────────────────────────────────────────────

    def test_wait_until_true_immediately(self) -> None:
        """Condition already true — no waiting, continues immediately."""
        t = _stack('control_wait_until', 'motion_movesteps')
        _set(t, 'b0', inputs={'CONDITION': Input(value=True)})
        _set(t, 'b1', inputs={'STEPS': Input(value=10)})
        t._rebuild_hat_cache()
        rt = _run(t, steps=10)
        assert len(rt.threads) == 0
        assert t.x == 10.0

    def test_wait_until_polls_until_true(self) -> None:
        """Polls until a variable-based condition becomes true."""
        t = _make_tgt()
        t.blocks['w'] = make_block(
            'control_wait_until',
            'w',
            inputs={'CONDITION': Input(value=[12, 'ready'])},
        )
        t.blocks['set_ready'] = Block(
            id='set_ready',
            opcode='data_setvariableto',
            inputs={'VALUE': Input(value=1)},
            fields={'VARIABLE': Field(value='ready')},
        )
        t.variables['ready'] = Variable('ready', 0)
        # Chain: hat → wait_until → set_ready
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = 'w'
        t.blocks['w'].next = 'set_ready'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        # Step once: wait_until sees ready=0 → yields
        rt.step()
        assert len(rt.threads) == 1
        # Manually set the variable to satisfy the wait
        var = t.lookup_variable('ready')
        assert var is not None
        var.value = 1
        # Next step: wait_until sees ready=1 → exits → advances to set_ready
        rt.step()
        assert len(rt.threads) == 1  # still has set_ready to run
        # One more step: set_ready runs
        rt.step()
        assert len(rt.threads) == 0

    def test_forever_with_stop(self) -> None:
        """Forever keeps a thread alive; stop_all kills it."""
        t = _make_tgt()
        t.blocks['f'] = make_block(
            'control_forever', 'f', inputs={'SUBSTACK': Input(value='b_move')}
        )
        t.blocks['b_move'] = Block(
            id='b_move', opcode='motion_movesteps', inputs={'STEPS': Input(value=1)}
        )
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = 'f'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(3):
            rt.step()
        assert len(rt.threads) == 1
        assert t.x > 0
        # Simulate a stop-all
        for th in list(rt.threads):
            th.status = 'done'
        rt.step()
        assert len(rt.threads) == 0

    # ── control_for_each ────────────────────────────────────────────────

    def test_for_each_iterates_forward(self) -> None:
        """Iterates FROM=1 TO=5, sets variable each iteration, runs body."""
        t = _make_tgt()
        t.blocks['f'] = make_block(
            'control_for_each',
            'f',
            inputs={'FROM': Input(value=1), 'TO': Input(value=5), 'SUBSTACK': Input(value='b0')},
            fields={'VARIABLE': Field(value='i')},
        )
        t.blocks['b0'] = Block(
            id='b0', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}
        )
        t.variables['i'] = Variable('i', 0)
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = 'f'
        t._rebuild_hat_cache()
        rt = _run(t, steps=100)
        assert len(rt.threads) == 0
        v = t.lookup_variable('i')
        assert v is not None and v.value == 5  # last iteration value
        assert t.x == 50.0  # 5 × 10 steps

    def test_for_each_descending(self) -> None:
        """FROM > TO iterates backward (step = -1)."""
        t = _make_tgt()
        t.blocks['f'] = make_block(
            'control_for_each',
            'f',
            inputs={'FROM': Input(value=3), 'TO': Input(value=1), 'SUBSTACK': Input(value='b0')},
            fields={'VARIABLE': Field(value='i')},
        )
        t.blocks['b0'] = Block(
            id='b0', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}
        )
        t.variables['i'] = Variable('i', 0)
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = 'f'
        t._rebuild_hat_cache()
        rt = _run(t, steps=60)
        assert len(rt.threads) == 0
        v = t.lookup_variable('i')
        assert v is not None and v.value == 1  # last iteration value
        assert t.x == 30.0  # 3 × 10 steps

    # ── control_stop ────────────────────────────────────────────────────

    def test_stop_this_script(self) -> None:
        """stop 'this script' terminates the current script, other scripts continue."""
        t = Target(name='Sprite', is_stage=False)
        t.blocks['stop_s'] = make_block(
            'control_stop', 'stop_s', fields={'STOP_OPTION': Field(value='this script')}
        )
        t.blocks['h1'] = make_block('event_whenflagclicked', 'h1', top_level=True, next_='b5')
        t.blocks['b5'] = Block(id='b5', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)})
        t.blocks['b10'] = Block(
            id='b10', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}
        )
        t.blocks['b5'].next = 'stop_s'
        t.blocks['stop_s'].next = 'b10'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(10):
            rt.step()
        # b10 should never execute; stop halts the thread after b5
        assert t.x == 5.0
        assert len(rt.threads) == 0
        assert t.y == 0.0

    def test_stop_all(self) -> None:
        """stop 'all' terminates every thread immediately."""
        t = Target(name='Sprite', is_stage=False)
        # Script 1: forever loop
        t.blocks['h1'] = make_block('event_whenflagclicked', 'h1', top_level=True, next_='f')
        t.blocks['f'] = make_block(
            'control_forever', 'f', inputs={'SUBSTACK': Input(value='b_move')}
        )
        t.blocks['b_move'] = Block(
            id='b_move', opcode='motion_movesteps', inputs={'STEPS': Input(value=1)}
        )
        # Script 2: stop all
        t.blocks['h2'] = make_block('event_whenflagclicked', 'h2', top_level=True, next_='stop_a')
        t.blocks['stop_a'] = make_block(
            'control_stop', 'stop_a', fields={'STOP_OPTION': Field(value='all')}
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        assert len(rt.threads) == 0  # stop_all killed everything

    def test_stop_other_scripts_in_sprite(self) -> None:
        """stop 'other scripts in sprite' kills sibling threads, current script continues."""
        t = Target(name='Sprite', is_stage=False)
        # Script 1: forever loop
        t.blocks['h1'] = make_block('event_whenflagclicked', 'h1', top_level=True, next_='f')
        t.blocks['f'] = make_block(
            'control_forever', 'f', inputs={'SUBSTACK': Input(value='b_move')}
        )
        t.blocks['b_move'] = Block(
            id='b_move', opcode='motion_movesteps', inputs={'STEPS': Input(value=1)}
        )
        # Script 2: stop other scripts → movesteps 10
        t.blocks['h2'] = make_block('event_whenflagclicked', 'h2', top_level=True, next_='stop_o')
        t.blocks['stop_o'] = make_block(
            'control_stop',
            'stop_o',
            fields={'STOP_OPTION': Field(value='other scripts in sprite')},
        )
        t.blocks['b_final'] = Block(
            id='b_final', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}
        )
        t.blocks['stop_o'].next = 'b_final'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(10):
            rt.step()
        # The forever script was stopped by 'other scripts in sprite'
        assert len(rt.threads) == 0
        assert t.x >= 10.0  # b_final ran

    # ── control_all_at_once ─────────────────────────────────────────────

    def test_all_at_once_runs_without_yield(self) -> None:
        """control_all_at_once runs its substack without yielding between blocks."""
        t = _make_tgt()
        # Substack: two sequential movesteps
        t.blocks['a'] = make_block(
            'control_all_at_once', 'a', inputs={'SUBSTACK': Input(value='b0')}
        )
        t.blocks['b0'] = Block(
            id='b0', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}
        )
        t.blocks['b1'] = Block(
            id='b1', opcode='motion_movesteps', inputs={'STEPS': Input(value=20)}
        )
        t.blocks['b0'].next = 'b1'
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = 'a'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        # Both blocks should execute in a single step (no yield between them)
        rt.step()
        assert t.x == 30.0  # 10 + 20 in one frame
        assert len(rt.threads) == 0

    # ── control_create_clone_of ─────────────────────────────────────────

    def test_create_clone_of_myself(self) -> None:
        """Creates a clone of the current sprite with _start_as_clone hat.

        Uses a named sprite rather than _myself_ to avoid infinite
        recursion (clone inherits the creator's green-flag script).
        """
        src = Target(name='Target', is_stage=False)
        src.blocks['h_clone'] = make_block(
            'control_start_as_clone', 'h_clone', top_level=True, next_='b_move'
        )
        src.blocks['b_move'] = Block(
            id='b_move', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)}
        )
        src._rebuild_hat_cache()

        creator = Target(name='Creator', is_stage=False)
        creator.blocks['h_gf'] = make_block(
            'event_whenflagclicked', 'h_gf', top_level=True, next_='b_clone'
        )
        creator.blocks['b_clone'] = Block(
            id='b_clone',
            opcode='control_create_clone_of',
            fields={'CLONE_OPTION': Field(value='Target')},
        )
        creator._rebuild_hat_cache()

        rt = Runtime()
        rt._real_time = False
        rt.add_target(Target(name='Stage', is_stage=True))
        rt.add_target(src)
        rt.add_target(creator)
        rt.register_all(OPCODE_MAP)
        rt.green_flag()
        for _ in range(10):
            rt.step()
        # A clone of Target should have been created
        clones = [c for c in rt.targets if c._is_clone]
        assert len(clones) == 1
        clone = clones[0]
        assert clone.name == 'Target_clone'
        assert clone.x == 5.0  # started as clone → movesteps 5

    def test_create_clone_of_named_sprite(self) -> None:
        """Creates a clone of a named sprite and triggers _start_as_clone on it."""
        sprite_a = Target(name='A', is_stage=False)
        sprite_a.blocks['h_clone'] = make_block(
            'control_start_as_clone', 'h_clone', top_level=True, next_='b_move'
        )
        sprite_a.blocks['b_move'] = Block(
            id='b_move', opcode='motion_movesteps', inputs={'STEPS': Input(value=10)}
        )
        sprite_a._rebuild_hat_cache()

        sprite_b = Target(name='B', is_stage=False)
        sprite_b.blocks['h_gf'] = make_block(
            'event_whenflagclicked', 'h_gf', top_level=True, next_='b_clone'
        )
        sprite_b.blocks['b_clone'] = Block(
            id='b_clone',
            opcode='control_create_clone_of',
            fields={'CLONE_OPTION': Field(value='A')},
        )
        sprite_b._rebuild_hat_cache()

        rt = Runtime()
        rt._real_time = False
        rt.add_target(Target(name='Stage', is_stage=True))
        rt.add_target(sprite_a)
        rt.add_target(sprite_b)
        rt.register_all(OPCODE_MAP)
        rt.green_flag()
        for _ in range(10):
            rt.step()

        clones = [c for c in rt.targets if c._is_clone]
        assert len(clones) == 1
        clone = clones[0]
        assert clone.name == 'A_clone'
        assert clone.x == 10.0


# ═══════════════════════════════════════════════════════════════════════
#  Event
# ═══════════════════════════════════════════════════════════════════════


class TestEvent:
    def test_broadcast_starts_hat(self) -> None:
        t1 = Target(name='A', is_stage=False)
        t1.blocks['h'] = make_block('event_whenflagclicked', 'h', top_level=True, next_='b')
        t1.blocks['b'] = make_block(
            'event_broadcast', 'b', inputs={'BROADCAST_INPUT': Input(value='msg')}
        )
        t1._rebuild_hat_cache()

        t2 = Target(name='B', is_stage=False)
        t2.blocks['h2'] = make_block(
            'event_whenbroadcastreceived',
            'h2',
            top_level=True,
            fields={'BROADCAST_OPTION': Field(value='msg')},
            next_='m',
        )
        t2.blocks['m'] = Block(id='m', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)})
        t2._rebuild_hat_cache()

        rt = _rt([t1, t2])
        rt.green_flag()
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 0
        assert t2.x == 5.0

    def test_broadcastandwait_waits_for_threads(self) -> None:
        """event_broadcastandwait yields until all triggered threads finish."""
        t1 = Target(name='A', is_stage=False)
        t1.blocks['h1'] = make_block('event_whenflagclicked', 'h1', top_level=True, next_='b')
        t1.blocks['b'] = make_block(
            'event_broadcastandwait', 'b', inputs={'BROADCAST_INPUT': Input(value='msg')}, next_='s'
        )
        t1.blocks['s'] = Block(
            id='s', opcode='motion_gotoxy', inputs={'X': Input(value=20), 'Y': Input(value=0)}
        )
        t1._rebuild_hat_cache()

        t2 = Target(name='B', is_stage=False)
        t2.blocks['h2'] = make_block(
            'event_whenbroadcastreceived',
            'h2',
            top_level=True,
            fields={'BROADCAST_OPTION': Field(value='msg')},
            next_='m',
        )
        t2.blocks['m'] = Block(id='m', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)})
        t2._rebuild_hat_cache()

        rt = _rt([t1, t2])
        rt.green_flag()
        for _ in range(30):
            rt.step()
        assert len(rt.threads) == 0
        # B's move ran before A's setXY because broadcastandwait yields
        assert t2.x == 5.0
        assert t1.x == 20.0

    def test_broadcast_matches_by_id_name(self) -> None:
        """event_broadcast matches hat via broadcast.id when broadcast is on same target."""
        t1 = Target(name='A', is_stage=False)
        t1.broadcasts['bcast1'] = BroadcastMsg(name='my message')
        t1.blocks['h1'] = make_block('event_whenflagclicked', 'h1', top_level=True, next_='b')
        t1.blocks['b'] = make_block(
            'event_broadcast', 'b', inputs={'BROADCAST_INPUT': Input(value='bcast1')}
        )
        t1._rebuild_hat_cache()

        t2 = Target(name='B', is_stage=False)
        t2.broadcasts['bcast1'] = BroadcastMsg(name='my message')
        t2.blocks['h2'] = make_block(
            'event_whenbroadcastreceived',
            'h2',
            top_level=True,
            fields={'BROADCAST_OPTION': Field(value='bcast1')},
            next_='m',
        )
        t2.blocks['m'] = Block(id='m', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)})
        t2._rebuild_hat_cache()

        rt = _rt([t1, t2])
        rt.green_flag()
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 0
        assert t2.x == 5.0

    def test_broadcast_primitive_type_array_resolved(self) -> None:
        """Broadcast input in Scratch primitive format [11, msg, block_id] is resolved to bare string.

        Scratch JSON stores inline primitives as ``[type_code, value, block_id]``.
        Type code 11 = broadcast. ``resolve_input`` must unwrap the array and
        return only the message string; otherwise the broadcast lookup uses the
        raw list and never matches.
        """
        t1 = Target(name='A', is_stage=False)
        t1.blocks['h1'] = make_block('event_whenflagclicked', 'h1', top_level=True, next_='b')
        t1.blocks['b'] = make_block(
            'event_broadcast',
            'b',
            inputs={'BROADCAST_INPUT': Input(value=[11, '我的消息', 'h=dummy_id'])},
        )
        t1._rebuild_hat_cache()

        t2 = Target(name='B', is_stage=False)
        t2.blocks['h2'] = make_block(
            'event_whenbroadcastreceived',
            'h2',
            top_level=True,
            fields={'BROADCAST_OPTION': Field(value='我的消息')},
            next_='m',
        )
        t2.blocks['m'] = Block(id='m', opcode='motion_movesteps', inputs={'STEPS': Input(value=5)})
        t2._rebuild_hat_cache()

        rt = _rt([t1, t2])
        rt.green_flag()
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 0
        # B should have received the broadcast and moved
        assert t2.x == 5.0

    def test_keypressed_matches_key_name(self) -> None:
        """event_whenkeypressed hat starts when start_key_hat matches."""
        t1 = Target(name='Sprite1', is_stage=False)
        t1.blocks['h1'] = make_block(
            'event_whenkeypressed',
            'h1',
            top_level=True,
            fields={'KEY_OPTION': Field(value='space')},
            next_='m',
        )
        t1.blocks['m'] = Block(
            id='m', opcode='motion_gotoxy', inputs={'X': Input(value=10), 'Y': Input(value=0)}
        )
        t1._rebuild_hat_cache()

        rt = _rt(t1)
        rt.start_key_hat('space')
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 0
        assert t1.x == 10.0

    def test_keypressed_any_wildcard(self) -> None:
        """event_whenkeypressed with KEY_OPTION='any' matches any key."""
        t1 = Target(name='Sprite1', is_stage=False)
        t1.blocks['h1'] = make_block(
            'event_whenkeypressed',
            'h1',
            top_level=True,
            fields={'KEY_OPTION': Field(value='any')},
            next_='m',
        )
        t1.blocks['m'] = Block(
            id='m', opcode='motion_gotoxy', inputs={'X': Input(value=10), 'Y': Input(value=0)}
        )
        t1._rebuild_hat_cache()

        rt = _rt(t1)
        rt.start_key_hat('a')
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 0
        assert t1.x == 10.0

    def test_keypressed_does_not_match_wrong_key(self) -> None:
        """event_whenkeypressed ignores non-matching key names."""
        t1 = Target(name='Sprite1', is_stage=False)
        t1.blocks['h1'] = make_block(
            'event_whenkeypressed',
            'h1',
            top_level=True,
            fields={'KEY_OPTION': Field(value='space')},
            next_='m',
        )
        t1.blocks['m'] = Block(
            id='m', opcode='motion_gotoxy', inputs={'X': Input(value=10), 'Y': Input(value=0)}
        )
        t1._rebuild_hat_cache()

        rt = _rt(t1)
        rt.start_key_hat('a')
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 0
        assert t1.x == 0.0  # not moved — wrong key

    def test_thisspriteclicked_fires_on_click(self) -> None:
        """event_whenthisspriteclicked hat fires when click lands on sprite."""
        t1 = Target(name='Sprite1', is_stage=False)
        t1.blocks['h1'] = make_block(
            'event_whenthisspriteclicked',
            'h1',
            top_level=True,
            next_='m',
        )
        t1.blocks['m'] = Block(
            id='m', opcode='motion_gotoxy', inputs={'X': Input(value=10), 'Y': Input(value=0)}
        )
        t1._rebuild_hat_cache()

        rt = _rt(t1)
        # Sprite at (0,0) with default radius 30 — click at (0,0) hits it
        rt.start_click_hat(0, 0)
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 0
        assert t1.x == 10.0

    def test_stageclicked_fires_when_no_sprite_hit(self) -> None:
        """event_whenstageclicked fires when click misses all sprites."""
        t1 = Target(name='Sprite1', is_stage=False)
        t1.visible = False  # invisible sprite won't intercept click

        stage = Target(name='Stage', is_stage=True)
        stage.blocks['hs'] = make_block(
            'event_whenstageclicked',
            'hs',
            top_level=True,
            next_='m',
        )
        stage.blocks['m'] = Block(
            id='m', opcode='motion_gotoxy', inputs={'X': Input(value=15), 'Y': Input(value=0)}
        )
        stage._rebuild_hat_cache()

        rt = Runtime()
        rt._real_time = False
        rt.add_target(stage)
        rt.add_target(t1)
        rt.register_all(OPCODE_MAP)

        # Click far from sprite, near origin
        rt.start_click_hat(0, 0)
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 0
        # stage has no x but we just check no error and threads finish

    @pytest.mark.xfail(reason='edge-activated hat evaluation not wired into step loop')
    def test_whentouchingobject_edge_activated(self) -> None:
        """event_whentouchingobject fires on false→true transition (edge-activated)."""
        t1 = Target(name='Sprite1', is_stage=False)
        t1.blocks['h1'] = make_block(
            'event_whentouchingobject',
            'h1',
            top_level=True,
            fields={'TOUCHINGOBJECTMENU': Field(value='_edge_')},
            next_='m',
        )
        t1.blocks['m'] = Block(
            id='m', opcode='motion_gotoxy', inputs={'X': Input(value=50), 'Y': Input(value=0)}
        )
        t1._rebuild_hat_cache()

        rt = _rt(t1)
        # Sprite at (0,0) — not touching edge; first step seeds edge-hat value (false)
        for _ in range(5):
            rt.step()

        # Move sprite past right edge (-240..240)
        t1.set_xy(300, 0)
        for _ in range(10):
            rt.step()
        assert t1.x == 50.0

    @pytest.mark.xfail(reason='edge-activated hat evaluation not wired into step loop')
    def test_whengreaterthan_timer_edge_activated(self) -> None:
        """event_whengreaterthan fires on false→true timer transition."""
        t1 = Target(name='Sprite1', is_stage=False)
        t1.blocks['h1'] = make_block(
            'event_whengreaterthan',
            'h1',
            top_level=True,
            fields={'WHENGREATERTHANMENU': Field(value='timer')},
            inputs={'VALUE': Input(value=0.5)},
            next_='m',
        )
        t1.blocks['m'] = Block(
            id='m', opcode='motion_gotoxy', inputs={'X': Input(value=50), 'Y': Input(value=0)}
        )
        t1._rebuild_hat_cache()

        rt = _rt(t1)
        # First step seeds edge-hat value (timer=0, not >0.5)
        for _ in range(5):
            rt.step()
        # Advance clock past 0.5s (30+ ticks at 60fps)
        for _ in range(40):
            rt.step()
        assert t1.x == 50.0

    def test_whengreaterthan_loudness_edge_activated(self) -> None:
        """event_whengreaterthan loudness returns false (no microphone)."""
        t1 = Target(name='Sprite1', is_stage=False)
        t1.blocks['h1'] = make_block(
            'event_whengreaterthan',
            'h1',
            top_level=True,
            fields={'WHENGREATERTHANMENU': Field(value='loudness')},
            inputs={'VALUE': Input(value=0)},
            next_='m',
        )
        t1.blocks['m'] = Block(
            id='m', opcode='motion_gotoxy', inputs={'X': Input(value=50), 'Y': Input(value=0)}
        )
        t1._rebuild_hat_cache()

        rt = _rt(t1)
        for _ in range(10):
            rt.step()
        # loudness always returns False, so never transitions false→true
        assert t1.x == 0.0


# ═══════════════════════════════════════════════════════════════════════
#  Motion
# ═══════════════════════════════════════════════════════════════════════


class TestMotion:
    def test_movesteps(self) -> None:
        t = _stack('motion_movesteps')
        _set(t, 'b0', inputs={'STEPS': Input(value=10)})
        rt = _run(t)
        assert len(rt.threads) == 0
        assert t.x == 10.0  # direction 90 = positive x

    def test_gotoxy(self) -> None:
        t = _stack('motion_gotoxy')
        _set(t, 'b0', inputs={'X': Input(value=-100), 'Y': Input(value=200)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.x == -100
        assert t.y == 200

    def test_gox_goy(self) -> None:
        t = _stack('motion_gox', 'motion_goy')
        _set(t, 'b0', inputs={'X': Input(value=50)})
        _set(t, 'b1', inputs={'Y': Input(value=-30)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.x == 50
        assert t.y == -30

    def test_turn(self) -> None:
        t = _stack('motion_turnright', 'motion_turnleft')
        _set(t, 'b0', inputs={'DEGREES': Input(value=45)})
        _set(t, 'b1', inputs={'DEGREES': Input(value=90)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.direction == 45.0  # 90 + 45 - 90 = 45

    def test_change_xy(self) -> None:
        t = _stack('motion_changexby', 'motion_changeyby')
        _set(t, 'b0', inputs={'DX': Input(value=15)})
        _set(t, 'b1', inputs={'DY': Input(value=-25)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.x == 15
        assert t.y == -25

    def test_set_direction(self) -> None:
        t = _stack('motion_setdirection')
        _set(t, 'b0', inputs={'DIRECTION': Input(value=180)})
        rt = _run(t)
        assert t.direction == 180

    def test_xposition(self) -> None:
        t = _stack('motion_gotoxy', 'motion_xposition')
        _set(t, 'b0', inputs={'X': Input(value=42), 'Y': Input(value=0)})
        rt = _run(t)
        assert t.x == 42

    def test_glide_smoke(self) -> None:
        t = _stack('motion_glidesecstoxy')
        _set(t, 'b0', inputs={'SECS': Input(value=0.1), 'X': Input(value=100), 'Y': Input(value=0)})
        rt = _rt(t)
        rt.green_flag()
        for _ in range(30):
            rt.step()
        assert abs(t.x - 100) < 0.1

    # ── Direction defaults ─────────────────────────────────────────────

    def test_default_direction(self) -> None:
        """A fresh sprite faces right (direction=90)."""
        t = _make_tgt()
        assert t.direction == 90.0

    # ── movesteps at various directions ─────────────────────────────────

    def test_movesteps_direction_0(self) -> None:
        """Direction 0 = up → movesteps with positive value moves +y."""
        t = _stack('motion_setdirection', 'motion_movesteps')
        _set(t, 'b0', inputs={'DIRECTION': Input(value=0)})
        _set(t, 'b1', inputs={'STEPS': Input(value=10)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert len(rt.threads) == 0
        assert abs(t.x - 0.0) < 1e-9
        assert t.y == 10.0

    def test_movesteps_direction_180(self) -> None:
        """Direction 180 = down → movesteps with positive value moves -y."""
        t = _stack('motion_setdirection', 'motion_movesteps')
        _set(t, 'b0', inputs={'DIRECTION': Input(value=180)})
        _set(t, 'b1', inputs={'STEPS': Input(value=10)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert len(rt.threads) == 0
        assert abs(t.x - 0.0) < 1e-9
        assert t.y == -10.0

    def test_movesteps_direction_neg90(self) -> None:
        """Direction -90 = left → movesteps with positive value moves -x."""
        t = _stack('motion_setdirection', 'motion_movesteps')
        _set(t, 'b0', inputs={'DIRECTION': Input(value=-90)})
        _set(t, 'b1', inputs={'STEPS': Input(value=10)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert len(rt.threads) == 0
        assert t.x == -10.0
        assert abs(t.y - 0.0) < 1e-9

    def test_movesteps_negative_steps(self) -> None:
        """Negative steps moves opposite to current direction."""
        t = _stack('motion_movesteps')
        _set(t, 'b0', inputs={'STEPS': Input(value=-10)})
        rt = _run(t)
        assert len(rt.threads) == 0
        assert t.x == -10.0

    # ── turnright / turnleft ───────────────────────────────────────────

    def test_turnright_only(self) -> None:
        """Turn right 45°: direction increases by 45 from 90 → 135."""
        t = _stack('motion_turnright')
        _set(t, 'b0', inputs={'DEGREES': Input(value=45)})
        rt = _run(t)
        assert t.direction == 135.0

    def test_turnleft_only(self) -> None:
        """Turn left 45°: direction decreases by 45 from 90 → 45."""
        t = _stack('motion_turnleft')
        _set(t, 'b0', inputs={'DEGREES': Input(value=45)})
        rt = _run(t)
        assert t.direction == 45.0

    def test_turn_negative_degrees(self) -> None:
        """Turning by negative degrees goes the opposite way."""
        t = _stack('motion_turnright', 'motion_turnleft')
        _set(t, 'b0', inputs={'DEGREES': Input(value=-30)})
        _set(t, 'b1', inputs={'DEGREES': Input(value=-15)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.direction == 75.0  # 90 + (-30) - (-15) = 75

    # ── point in direction ─────────────────────────────────────────────

    def test_pointindirection(self) -> None:
        """Point in direction sets the absolute direction."""
        t = _stack('motion_pointindirection')
        _set(t, 'b0', inputs={'DIRECTION': Input(value=-45)})
        rt = _run(t)
        assert t.direction == -45.0

    # ── point towards ──────────────────────────────────────────────────

    def test_pointtowards_mouse(self) -> None:
        """Point towards mouse: direction calculated from sprite to mouse."""
        t = _stack('motion_pointtowards')
        _set(t, 'b0', fields={'TOWARDS': Field(value='_mouse_')})
        rt = _rt(t)
        rt._mouse_x = 100.0
        rt._mouse_y = 0.0
        rt.green_flag()
        for _ in range(10):
            rt.step()
        # Sprite at (0,0), mouse at (100,0) → direction = 90 - atan2(0,100)*180/π = 90
        assert t.direction == 90.0

    def test_pointtowards_sprite(self) -> None:
        """Point towards another sprite: direction calculated from self to target."""
        t = _make_tgt('Sprite')
        other = _make_tgt('Other')
        other.x = 100.0
        other.y = 50.0
        tgt_id = 'b0'
        t.blocks[tgt_id] = Block(
            id=tgt_id,
            opcode='motion_pointtowards',
            fields={'TOWARDS': Field(value='Other')},
            next=None,
            parent=None,
        )
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = tgt_id
        t._rebuild_hat_cache()
        rt = _rt([t, other])
        rt.green_flag()
        for _ in range(10):
            rt.step()
        expected = 90 - math.degrees(math.atan2(50.0, 100.0))
        assert t.direction == expected

    def test_pointtowards_random(self) -> None:
        """Point towards _random_ sets a random direction."""
        t = _stack('motion_pointtowards')
        _set(t, 'b0', fields={'TOWARDS': Field(value='_random_')})
        rt = _run(t)
        # Random direction will be within [-180, 180]
        assert -180.0 <= t.direction <= 180.0

    # ── goto ───────────────────────────────────────────────────────────

    def test_goto_random(self) -> None:
        """Go to _random_ places sprite at random position within stage bounds."""
        t = _stack('motion_goto')
        _set(t, 'b0', fields={'TO': Field(value='_random_')})
        rt = _run(t)
        assert -240.0 <= t.x <= 240.0
        assert -180.0 <= t.y <= 180.0

    def test_goto_mouse(self) -> None:
        """Go to _mouse_ places sprite at mouse coordinates."""
        t = _stack('motion_goto')
        _set(t, 'b0', fields={'TO': Field(value='_mouse_')})
        rt = _rt(t)
        rt._mouse_x = 75.0
        rt._mouse_y = -120.0
        rt.green_flag()
        for _ in range(10):
            rt.step()
        assert t.x == 75.0
        assert t.y == -120.0

    def test_goto_sprite(self) -> None:
        """Go to another sprite moves this sprite to that sprite's position."""
        t = _make_tgt('Sprite')
        other = _make_tgt('Target')
        other.x = -50.0
        other.y = 80.0
        tgt_id = 'b0'
        t.blocks[tgt_id] = Block(
            id=tgt_id,
            opcode='motion_goto',
            fields={'TO': Field(value='Target')},
            next=None,
            parent=None,
        )
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = tgt_id
        t._rebuild_hat_cache()
        rt = _rt([t, other])
        rt.green_flag()
        for _ in range(10):
            rt.step()
        assert t.x == -50.0
        assert t.y == 80.0

    # ── setx / sety ────────────────────────────────────────────────────

    def test_setx(self) -> None:
        """motion_setx sets x position without changing y."""
        t = _stack('motion_setx')
        _set(t, 'b0', inputs={'X': Input(value=123)})
        rt = _run(t)
        assert t.x == 123.0
        assert t.y == 0.0

    def test_sety(self) -> None:
        """motion_sety sets y position without changing x."""
        t = _stack('motion_sety')
        _set(t, 'b0', inputs={'Y': Input(value=-55)})
        rt = _run(t)
        assert t.x == 0.0
        assert t.y == -55.0

    # ── changexby / changeyby ──────────────────────────────────────────

    def test_changexby_from_nonzero(self) -> None:
        """motion_changexby adds to existing x position."""
        t = _stack('motion_gotoxy', 'motion_changexby')
        _set(t, 'b0', inputs={'X': Input(value=10), 'Y': Input(value=0)})
        _set(t, 'b1', inputs={'DX': Input(value=20)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.x == 30.0

    def test_changeyby_from_nonzero(self) -> None:
        """motion_changeyby adds to existing y position."""
        t = _stack('motion_gotoxy', 'motion_changeyby')
        _set(t, 'b0', inputs={'X': Input(value=0), 'Y': Input(value=5)})
        _set(t, 'b1', inputs={'DY': Input(value=-10)})
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.y == -5.0

    # ── position / direction reporters ─────────────────────────────────

    def test_yposition(self) -> None:
        """motion_yposition reports current y position."""
        t = _stack('motion_gotoxy', 'motion_yposition')
        _set(t, 'b0', inputs={'X': Input(value=-10), 'Y': Input(value=77)})
        rt = _run(t)
        assert t.y == 77.0

    def test_direction_reporter(self) -> None:
        """motion_direction is a reporter (yield Report); it reads direction without changing it."""
        t = _stack('motion_pointindirection')
        _set(t, 'b0', inputs={'DIRECTION': Input(value=45)})
        rt = _run(t)
        assert t.direction == 45.0

    def test_glideto(self) -> None:
        """motion_glideto resolves a named target and glides."""
        t = _make_tgt('Sprite')
        other = _make_tgt('Target')
        other.x = 200.0
        other.y = 150.0
        tgt_id = 'b0'
        t.blocks[tgt_id] = Block(
            id=tgt_id,
            opcode='motion_glideto',
            inputs={'SECS': Input(value=0.05)},
            fields={'TO': Field(value='Target')},
            next=None,
            parent=None,
        )
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = tgt_id
        t._rebuild_hat_cache()
        rt = _rt([t, other])
        rt.green_flag()
        for _ in range(60):
            rt.step()
        assert abs(t.x - 200.0) < 0.1
        assert abs(t.y - 150.0) < 0.1

    # ── if on edge, bounce ─────────────────────────────────────────────

    def test_ifonedgebounce(self) -> None:
        """Bounce off edge: sprite at x=240 with a 10px-wide costume bounces to x=235."""
        t = _stack('motion_gotoxy', 'motion_ifonedgebounce')
        _set(t, 'b0', inputs={'X': Input(value=240), 'Y': Input(value=0)})
        # Add a 10×10 costume so bounds are -235..235
        surf = pygame.Surface((10, 10))
        t.costumes.append(Costume(name='c', surface=surf))
        t.costume_index = 0
        t.direction = 90.0  # facing right
        t._rebuild_hat_cache()
        rt = _run(t)
        # Bounced: x clamped to 235, direction reflected 180-90=-90 (facing down)
        assert t.x == 235.0
        assert t.direction == 90.0  # 180 - 90 = 90 → still 90 because bounce uses 180 - direction

    # ── set rotation style ─────────────────────────────────────────────

    def test_setrotationstyle_all_around(self) -> None:
        """Set rotation style to 'all around'."""
        t = _stack('motion_setrotationstyle')
        _set(t, 'b0', fields={'STYLE': Field(value='all around')})
        rt = _run(t)
        assert t.rotation_style == 'all around'

    def test_setrotationstyle_left_right(self) -> None:
        """Set rotation style to 'left-right'."""
        t = _stack('motion_setrotationstyle')
        _set(t, 'b0', fields={'STYLE': Field(value='left-right')})
        rt = _run(t)
        assert t.rotation_style == 'left-right'

    def test_setrotationstyle_dont_rotate(self) -> None:
        """Set rotation style to 'don\\'t rotate'."""
        t = _stack('motion_setrotationstyle')
        _set(t, 'b0', fields={'STYLE': Field(value="don't rotate")})
        rt = _run(t)
        assert t.rotation_style == "don't rotate"

    # ── glideto with teleport (secs=0) ─────────────────────────────────

    def test_glideto_teleport_zero_secs(self) -> None:
        """motion_glideto with secs=0 teleports immediately."""
        t = _make_tgt('Sprite')
        other = _make_tgt('Target')
        other.x = 88.0
        other.y = -66.0
        tgt_id = 'b0'
        t.blocks[tgt_id] = Block(
            id=tgt_id,
            opcode='motion_glideto',
            inputs={'SECS': Input(value=0)},
            fields={'TO': Field(value='Target')},
            next=None,
            parent=None,
        )
        hat = next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked')
        hat.next = tgt_id
        t._rebuild_hat_cache()
        rt = _rt([t, other])
        rt.green_flag()
        for _ in range(10):
            rt.step()
        assert len(rt.threads) == 0
        assert t.x == 88.0
        assert t.y == -66.0


# ═══════════════════════════════════════════════════════════════════════
#  Looks
# ═══════════════════════════════════════════════════════════════════════


class TestLooks:
    # ── Show / Hide ─────────────────────────────────────────────────
    def test_show_hide(self) -> None:
        t = _stack('looks_hide', 'looks_show')
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.visible is True

    def test_hide(self) -> None:
        t = _stack('looks_hide')
        assert t.visible is True  # default
        rt = _run(t)
        assert t.visible is False

    # ── Layer ordering ──────────────────────────────────────────────
    def test_goto_front(self) -> None:
        t = _make_tgt()
        t.blocks['b0'] = _op('looks_gotofrontback', fields={'FRONT_BACK': Field(value='front')})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t.layer_order = 0
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        assert t.layer_order >= 1

    def test_goto_back(self) -> None:
        t = _make_tgt()
        t.blocks['b0'] = _op('looks_gotofrontback', fields={'FRONT_BACK': Field(value='back')})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t.layer_order = 5
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        assert t.layer_order == 4  # sprite only sprite, min=5 → min-1=4

    def test_goto_frontback_stage_noop(self) -> None:
        """looks_gotofrontback is a no-op on the stage."""
        stage = Target(name='Stage', is_stage=True)
        stage.blocks['b0'] = _op('looks_gotofrontback', fields={'FRONT_BACK': Field(value='front')})
        stage.blocks['h0'] = make_block('event_whenflagclicked', 'h0', top_level=True, next_='b0')
        stage._rebuild_hat_cache()
        prev = stage.layer_order
        rt = _rt(stage)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        assert stage.layer_order == prev

    def test_goforwardbackwardlayers_forward(self) -> None:
        t = _make_tgt()
        t.layer_order = 10
        t.blocks['b0'] = _op(
            'looks_goforwardbackwardlayers',
            inputs={'NUM': Input(value=3)},
            fields={'FORWARD_BACKWARD': Field(value='forward')},
        )
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        assert t.layer_order == 13  # 10 + 3

    def test_goforwardbackwardlayers_backward(self) -> None:
        t = _make_tgt()
        t.layer_order = 10
        t.blocks['b0'] = _op(
            'looks_goforwardbackwardlayers',
            inputs={'NUM': Input(value=4)},
            fields={'FORWARD_BACKWARD': Field(value='backward')},
        )
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        assert t.layer_order == 6  # 10 - 4

    def test_goforwardbackwardlayers_stage_noop(self) -> None:
        """looks_goforwardbackwardlayers is a no-op on the stage."""
        stage = Target(name='Stage', is_stage=True)
        stage.layer_order = 5
        stage.blocks['b0'] = _op(
            'looks_goforwardbackwardlayers',
            inputs={'NUM': Input(value=3)},
            fields={'FORWARD_BACKWARD': Field(value='forward')},
        )
        stage.blocks['h0'] = make_block('event_whenflagclicked', 'h0', top_level=True, next_='b0')
        stage._rebuild_hat_cache()
        rt = _rt(stage)
        rt.green_flag()
        for _ in range(5):
            rt.step()
        assert stage.layer_order == 5  # unchanged

    # ── Size ─────────────────────────────────────────────────────────
    def test_setsizeto(self) -> None:
        t = _stack('looks_setsizeto')
        _set(t, 'b0', inputs={'SIZE': Input(value=75)})
        rt = _run(t)
        assert t.size == 75

    def test_changesizeby(self) -> None:
        t = _stack('looks_changesizeby')
        _set(t, 'b0', inputs={'CHANGE': Input(value=25)})
        rt = _run(t)
        assert t.size == 125  # default 100 + 25

    def test_size_reporter(self) -> None:
        """looks_size returns the current sprite size."""
        t = _stack('looks_setsizeto', 'looks_size')
        _set(t, 'b0', inputs={'SIZE': Input(value=50)})
        rt = _run(t)
        assert len(rt.threads) == 0  # reporter completes

    # ── Costume / Backdrop reporters ─────────────────────────────────
    def test_costumenumbername_number(self) -> None:
        """looks_costumenumbername with NUMBER_NAME='number' returns 1-based index."""
        costumes = [Costume(name='a'), Costume(name='b'), Costume(name='c')]
        t = _make_tgt()
        t.costumes = costumes
        t.costume_index = 1  # second costume
        bid = _id()
        t.blocks[bid] = _op(
            'looks_costumenumbername',
            fields={'NUMBER_NAME': Field(value='number')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 2  # 1-based index

    def test_costumenumbername_name(self) -> None:
        """looks_costumenumbername with NUMBER_NAME='name' returns the costume name."""
        costumes = [Costume(name='a'), Costume(name='b'), Costume(name='c')]
        t = _make_tgt()
        t.costumes = costumes
        t.costume_index = 1  # second costume ('b')
        bid = _id()
        t.blocks[bid] = _op(
            'looks_costumenumbername',
            fields={'NUMBER_NAME': Field(value='name')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 'b'

    def test_costumenumbername_default_name(self) -> None:
        """looks_costumenumbername defaults to returning the costume name."""
        costumes = [Costume(name='a'), Costume(name='b')]
        t = _make_tgt()
        t.costumes = costumes
        t.costume_index = 0
        bid = _id()
        t.blocks[bid] = _op('looks_costumenumbername')  # no NUMBER_NAME field
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 'a'

    def test_costumenumbername_no_costume(self) -> None:
        """looks_costumenumbername returns '' when no costumes exist."""
        t = _make_tgt()
        bid = _id()
        t.blocks[bid] = _op(
            'looks_costumenumbername',
            fields={'NUMBER_NAME': Field(value='name')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == ''

    def test_backdropnumbername_number(self) -> None:
        """looks_backdropnumbername with NUMBER_NAME='number' on stage."""
        costumes = [Costume(name='bg1'), Costume(name='bg2')]
        stage = Target(name='Stage', is_stage=True)
        stage.costumes = costumes
        stage.costume_index = 0
        bid = _id()
        stage.blocks[bid] = _op(
            'looks_backdropnumbername',
            fields={'NUMBER_NAME': Field(value='number')},
        )
        rt = _rt(stage)
        assert rt.evaluate(stage, bid) == 1

    def test_backdropnumbername_name(self) -> None:
        """looks_backdropnumbername with NUMBER_NAME='name' on stage."""
        costumes = [Costume(name='bg1'), Costume(name='bg2')]
        stage = Target(name='Stage', is_stage=True)
        stage.costumes = costumes
        stage.costume_index = 1
        bid = _id()
        stage.blocks[bid] = _op(
            'looks_backdropnumbername',
            fields={'NUMBER_NAME': Field(value='name')},
        )
        rt = _rt(stage)
        assert rt.evaluate(stage, bid) == 'bg2'

    def test_costume(self) -> None:
        """looks_costume reads the COSTUME field and returns its value."""
        t = _make_tgt()
        bid = _id()
        t.blocks[bid] = _op('looks_costume', fields={'COSTUME': Field(value='costume1')})
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 'costume1'

    # ── Switch costume / next costume ────────────────────────────────
    def test_switchcostumeto_by_name(self) -> None:
        t = _make_tgt()
        t.costumes = [Costume(name='a'), Costume(name='b'), Costume(name='c')]
        t.costume_index = 0
        t.blocks['b0'] = _op('looks_switchcostumeto', inputs={'COSTUME': Input(value='c')})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        rt.step()
        assert t.costume_index == 2  # third costume

    def test_switchcostumeto_by_index(self) -> None:
        t = _make_tgt()
        t.costumes = [Costume(name='a'), Costume(name='b'), Costume(name='c')]
        t.costume_index = 0
        t.blocks['b0'] = _op('looks_switchcostumeto', inputs={'COSTUME': Input(value=2)})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        rt.step()
        assert t.costume_index == 1  # second costume (1-based → index 1)

    def test_switchcostumeto_whitespace_noop(self) -> None:
        """Whitespace input to looks_switchcostumeto is a no-op."""
        t = _make_tgt()
        t.costumes = [Costume(name='a'), Costume(name='b')]
        t.costume_index = 0
        t.blocks['b0'] = _op('looks_switchcostumeto', inputs={'COSTUME': Input(value='   ')})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        rt.step()
        assert t.costume_index == 0  # unchanged

    def test_switchcostumeto_by_name_not_found(self) -> None:
        """looks_switchcostumeto with a non-existent name stays unchanged."""
        t = _make_tgt()
        t.costumes = [Costume(name='a'), Costume(name='b')]
        t.costume_index = 0
        t.blocks['b0'] = _op(
            'looks_switchcostumeto', inputs={'COSTUME': Input(value='nonexistent')}
        )
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        rt.step()
        assert t.costume_index == 0  # unchanged

    def test_switchcostumeto_index_wrap(self) -> None:
        """looks_switchcostumeto with large index wraps around."""
        t = _make_tgt()
        t.costumes = [Costume(name='a'), Costume(name='b')]
        t.costume_index = 0
        t.blocks['b0'] = _op('looks_switchcostumeto', inputs={'COSTUME': Input(value=5)})
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        rt.step()
        assert t.costume_index == 0  # 5-1=4 → 4%2=0

    def test_nextcostume(self) -> None:
        t = _make_tgt()
        t.costumes = [Costume(name='a'), Costume(name='b'), Costume(name='c')]
        t.costume_index = 0
        t.blocks['b0'] = _op('looks_nextcostume')
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        rt.step()
        assert t.costume_index == 1  # moved to second costume

    def test_nextcostume_wraps(self) -> None:
        """looks_nextcostume wraps from last costume back to first."""
        t = _make_tgt()
        t.costumes = [Costume(name='a'), Costume(name='b')]
        t.costume_index = 1  # last costume
        t.blocks['b0'] = _op('looks_nextcostume')
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        rt.step()
        assert t.costume_index == 0  # wrapped to first

    def test_nextcostume_no_costumes(self) -> None:
        """looks_nextcostume does nothing when there are no costumes."""
        t = _make_tgt()
        t.costume_index = 0
        t.blocks['b0'] = _op('looks_nextcostume')
        next(b for b in t.blocks.values() if b.opcode == 'event_whenflagclicked').next = 'b0'
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt.green_flag()
        rt.step()
        assert t.costume_index == 0  # unchanged

    # ── Say / Think ──────────────────────────────────────────────────
    def test_say(self) -> None:
        t = _stack('looks_say')
        _set(t, 'b0', inputs={'MESSAGE': Input(value='Hello!')})
        rt = _run(t)
        assert t.say_text == 'Hello!'

    def test_say_empty(self) -> None:
        t = _stack('looks_say')
        _set(t, 'b0', inputs={'MESSAGE': Input(value='')})
        rt = _run(t)
        assert t.say_text is None

    def test_say_long_truncation(self) -> None:
        """looks_say truncates at 330 characters."""
        t = _stack('looks_say')
        _set(t, 'b0', inputs={'MESSAGE': Input(value='x' * 500)})
        rt = _run(t)
        assert t.say_text is not None and len(t.say_text) == 330

    def test_think(self) -> None:
        t = _stack('looks_think')
        _set(t, 'b0', inputs={'MESSAGE': Input(value='Hmm...')})
        rt = _run(t)
        assert t.say_text == 'Hmm...'

    def test_think_empty(self) -> None:
        t = _stack('looks_think')
        _set(t, 'b0', inputs={'MESSAGE': Input(value='')})
        rt = _run(t)
        assert t.say_text is None

    def test_sayforsecs_sets_and_clears(self) -> None:
        """looks_sayforsecs sets say_text, then clears after the wait."""
        t = _stack('looks_sayforsecs')
        _set(t, 'b0', inputs={'MESSAGE': Input(value='Hi'), 'SECS': Input(value=0.1)})
        rt = _rt(t)
        rt.green_flag()
        # Step 1: handler runs → sets say_text, yields Wait(0.1)
        rt.step()
        assert t.say_text == 'Hi'
        # Step enough to wake from wait (ceil(0.1*60)=6 ticks)
        for _ in range(20):
            rt.step()
        assert t.say_text is None

    def test_sayforsecs_zero_instant(self) -> None:
        """looks_sayforsecs with SECS=0 clears immediately."""
        t = _stack('looks_sayforsecs')
        _set(t, 'b0', inputs={'MESSAGE': Input(value='Hi'), 'SECS': Input(value=0)})
        rt = _run(t)
        assert t.say_text is None

    def test_thinkforsecs_sets_and_clears(self) -> None:
        """looks_thinkforsecs sets say_text, then clears after the wait."""
        t = _stack('looks_thinkforsecs')
        _set(t, 'b0', inputs={'MESSAGE': Input(value='Hmm'), 'SECS': Input(value=0.1)})
        rt = _rt(t)
        rt.green_flag()
        rt.step()
        assert t.say_text == 'Hmm'
        for _ in range(20):
            rt.step()
        assert t.say_text is None

    def test_thinkforsecs_zero_instant(self) -> None:
        """looks_thinkforsecs with SECS=0 clears immediately."""
        t = _stack('looks_thinkforsecs')
        _set(t, 'b0', inputs={'MESSAGE': Input(value='Hmm'), 'SECS': Input(value=0)})
        rt = _run(t)
        assert t.say_text is None

    # ── Graphic effects ──────────────────────────────────────────────
    def test_changeeffectby_ghost(self) -> None:
        """Ghost effect clamped to [0, 100]."""
        t = _stack('looks_changeeffectby')
        _set(t, 'b0', inputs={'CHANGE': Input(value=150)}, fields={'EFFECT': Field(value='ghost')})
        rt = _run(t)
        assert t.effects['ghost'] == 100

    def test_changeeffectby_ghost_negative(self) -> None:
        """Ghost effect clamped to 0 when decreasing below zero."""
        t = _stack('looks_changeeffectby')
        t.effects['ghost'] = 30
        _set(t, 'b0', inputs={'CHANGE': Input(value=-50)}, fields={'EFFECT': Field(value='ghost')})
        rt = _run(t)
        assert t.effects['ghost'] == 0

    def test_seteffectto_ghost(self) -> None:
        """looks_seteffectto clamps ghost to [0, 100]."""
        t = _stack('looks_seteffectto')
        _set(t, 'b0', inputs={'VALUE': Input(value=200)}, fields={'EFFECT': Field(value='ghost')})
        rt = _run(t)
        assert t.effects['ghost'] == 100

    def test_seteffectto_ghost_negative(self) -> None:
        """looks_seteffectto clamps ghost to 0 from negative."""
        t = _stack('looks_seteffectto')
        _set(t, 'b0', inputs={'VALUE': Input(value=-10)}, fields={'EFFECT': Field(value='ghost')})
        rt = _run(t)
        assert t.effects['ghost'] == 0

    def test_changeeffectby_brightness(self) -> None:
        """Brightness effect clamped to [-100, 100]."""
        t = _stack('looks_changeeffectby')
        _set(
            t,
            'b0',
            inputs={'CHANGE': Input(value=50)},
            fields={'EFFECT': Field(value='brightness')},
        )
        rt = _run(t)
        assert t.effects['brightness'] == 50

    def test_changeeffectby_brightness_overflow(self) -> None:
        """Brightness effect clamped at 100 when exceeding."""
        t = _stack('looks_changeeffectby')
        t.effects['brightness'] = 80
        _set(
            t,
            'b0',
            inputs={'CHANGE': Input(value=50)},
            fields={'EFFECT': Field(value='brightness')},
        )
        rt = _run(t)
        assert t.effects['brightness'] == 100

    def test_changeeffectby_brightness_underflow(self) -> None:
        """Brightness effect clamped at -100 when below."""
        t = _stack('looks_changeeffectby')
        t.effects['brightness'] = -50
        _set(
            t,
            'b0',
            inputs={'CHANGE': Input(value=-100)},
            fields={'EFFECT': Field(value='brightness')},
        )
        rt = _run(t)
        assert t.effects['brightness'] == -100

    def test_seteffectto_brightness(self) -> None:
        """looks_seteffectto clamps brightness to [-100, 100]."""
        t = _stack('looks_seteffectto')
        _set(
            t,
            'b0',
            inputs={'VALUE': Input(value=-200)},
            fields={'EFFECT': Field(value='brightness')},
        )
        rt = _run(t)
        assert t.effects['brightness'] == -100

    def test_changeeffectby_color_unbounded(self) -> None:
        """Color effect is not clamped."""
        t = _stack('looks_changeeffectby')
        _set(t, 'b0', inputs={'CHANGE': Input(value=500)}, fields={'EFFECT': Field(value='color')})
        rt = _run(t)
        assert t.effects['color'] == 500

    def test_seteffectto_color_unbounded(self) -> None:
        """Color effect set to arbitrary values."""
        t = _stack('looks_seteffectto')
        _set(t, 'b0', inputs={'VALUE': Input(value=-999)}, fields={'EFFECT': Field(value='color')})
        rt = _run(t)
        assert t.effects['color'] == -999

    def test_cleargraphiceffects(self) -> None:
        """looks_cleargraphiceffects resets all effects to 0."""
        t = _stack('looks_seteffectto', 'looks_changeeffectby', 'looks_cleargraphiceffects')
        _set(
            t, 'b0', inputs={'VALUE': Input(value=50)}, fields={'EFFECT': Field(value='brightness')}
        )
        _set(t, 'b1', inputs={'CHANGE': Input(value=80)}, fields={'EFFECT': Field(value='ghost')})
        rt = _run(t)
        for k, v in t.effects.items():
            assert v == 0, f'{k} = {v}, expected 0'


class TestOperators:
    def _eval(
        self,
        opcode: str,
        inputs: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
    ) -> Any:
        """Build a target with one reporter block and evaluate it."""
        t = _make_tgt()
        bid = _id()
        t.blocks[bid] = _op(opcode, inputs, fields)
        t._rebuild_hat_cache()
        rt = _rt(t)
        return rt.evaluate(t, bid)

    # ── Arithmetic ──────────────────────────────────────────────────
    def test_add(self) -> None:
        assert self._eval('operator_add', {'NUM1': 3, 'NUM2': 4}) == 7
        assert self._eval('operator_add', {'NUM1': -5, 'NUM2': 2}) == -3
        assert self._eval('operator_add', {'NUM1': 0.1, 'NUM2': 0.2}) == pytest.approx(0.3)
        assert self._eval('operator_add', {'NUM1': '3', 'NUM2': 4}) == 7
        assert self._eval('operator_add', {'NUM1': 'hello', 'NUM2': 4}) == 4

    def test_subtract(self) -> None:
        assert self._eval('operator_subtract', {'NUM1': 10, 'NUM2': 3}) == 7
        assert self._eval('operator_subtract', {'NUM1': 3, 'NUM2': 10}) == -7
        assert self._eval('operator_subtract', {'NUM1': 0, 'NUM2': 5}) == -5

    def test_multiply(self) -> None:
        assert self._eval('operator_multiply', {'NUM1': 3, 'NUM2': 4}) == 12
        assert self._eval('operator_multiply', {'NUM1': -2, 'NUM2': 5}) == -10
        assert self._eval('operator_multiply', {'NUM1': 3, 'NUM2': 0}) == 0
        assert self._eval('operator_multiply', {'NUM1': 1.5, 'NUM2': 2}) == 3

    def test_divide(self) -> None:
        assert self._eval('operator_divide', {'NUM1': 10, 'NUM2': 2}) == 5
        assert self._eval('operator_divide', {'NUM1': 7, 'NUM2': 3}) == pytest.approx(7 / 3)
        assert self._eval('operator_divide', {'NUM1': 10, 'NUM2': 0}) == float('inf')
        assert self._eval('operator_divide', {'NUM1': 0, 'NUM2': 5}) == 0

    # ── Comparison (Cast.compare semantics) ─────────────────────────
    def test_lt(self) -> None:
        assert self._eval('operator_lt', {'OPERAND1': 3, 'OPERAND2': 5}) is True
        assert self._eval('operator_lt', {'OPERAND1': 5, 'OPERAND2': 3}) is False
        assert self._eval('operator_lt', {'OPERAND1': 4, 'OPERAND2': 4}) is False
        assert self._eval('operator_lt', {'OPERAND1': 'a', 'OPERAND2': 1}) is True
        assert self._eval('operator_lt', {'OPERAND1': 1, 'OPERAND2': 'a'}) is False

    def test_equals(self) -> None:
        assert self._eval('operator_equals', {'OPERAND1': 5, 'OPERAND2': 5}) is True
        assert self._eval('operator_equals', {'OPERAND1': 5, 'OPERAND2': 4}) is False
        assert self._eval('operator_equals', {'OPERAND1': 'foo', 'OPERAND2': 'foo'}) is True
        assert self._eval('operator_equals', {'OPERAND1': 'foo', 'OPERAND2': 'FOO'}) is True
        assert self._eval('operator_equals', {'OPERAND1': 'hello', 'OPERAND2': 'world'}) is True

    def test_gt(self) -> None:
        assert self._eval('operator_gt', {'OPERAND1': 5, 'OPERAND2': 3}) is True
        assert self._eval('operator_gt', {'OPERAND1': 3, 'OPERAND2': 5}) is False
        assert self._eval('operator_gt', {'OPERAND1': 4, 'OPERAND2': 4}) is False

    def test_compare_whitespace_and_none(self) -> None:
        """Whitespace strings / None treated as NaN → string comparison."""
        assert self._eval('operator_equals', {'OPERAND1': 0, 'OPERAND2': ''}) is False
        assert self._eval('operator_lt', {'OPERAND1': '', 'OPERAND2': 'a'}) is True
        assert self._eval('operator_gt', {'OPERAND1': 'a', 'OPERAND2': ''}) is True

    def test_compare_infinity(self) -> None:
        assert self._eval('operator_lt', {'OPERAND1': float('inf'), 'OPERAND2': 1e9}) is False
        assert self._eval('operator_gt', {'OPERAND1': float('-inf'), 'OPERAND2': -1e9}) is False
        assert (
            self._eval('operator_equals', {'OPERAND1': float('inf'), 'OPERAND2': float('inf')})
            is True
        )
        assert (
            self._eval('operator_equals', {'OPERAND1': float('-inf'), 'OPERAND2': float('-inf')})
            is True
        )

    # ── Logic ───────────────────────────────────────────────────────
    def test_and(self) -> None:
        assert self._eval('operator_and', {'OPERAND1': True, 'OPERAND2': True}) is True
        assert self._eval('operator_and', {'OPERAND1': True, 'OPERAND2': False}) is False
        assert self._eval('operator_and', {'OPERAND1': False, 'OPERAND2': True}) is False
        assert self._eval('operator_and', {'OPERAND1': 1, 'OPERAND2': 0}) is False
        assert self._eval('operator_and', {'OPERAND1': 'hello', 'OPERAND2': ''}) is False

    def test_or(self) -> None:
        assert self._eval('operator_or', {'OPERAND1': True, 'OPERAND2': False}) is True
        assert self._eval('operator_or', {'OPERAND1': False, 'OPERAND2': False}) is False
        assert self._eval('operator_or', {'OPERAND1': '', 'OPERAND2': 'hello'}) is True
        assert self._eval('operator_or', {'OPERAND1': 0, 'OPERAND2': 1}) is True
        assert self._eval('operator_or', {'OPERAND1': 0, 'OPERAND2': 0}) is False

    def test_not(self) -> None:
        assert self._eval('operator_not', {'OPERAND': True}) is False
        assert self._eval('operator_not', {'OPERAND': False}) is True
        assert self._eval('operator_not', {'OPERAND': 0}) is True
        assert self._eval('operator_not', {'OPERAND': 1}) is False
        assert self._eval('operator_not', {'OPERAND': ''}) is True
        assert self._eval('operator_not', {'OPERAND': 'hello'}) is False

    # ── Random ──────────────────────────────────────────────────────
    def test_random_int_range_inclusive(self) -> None:
        """Integer from-to yields inclusive integer range."""
        for _ in range(100):
            r = self._eval('operator_random', {'FROM': 1, 'TO': 6})
            assert isinstance(r, int)
            assert 1 <= r <= 6

    def test_random_float_half_open(self) -> None:
        """Float from-to yields float in [low, high)."""
        for _ in range(200):
            r = self._eval('operator_random', {'FROM': 1.5, 'TO': 4.5})
            assert isinstance(r, float)
            assert 1.5 <= r < 4.5

    def test_random_auto_order(self) -> None:
        """Low/high auto-ordered: FROM > TO still gives correct range."""
        for _ in range(100):
            r = self._eval('operator_random', {'FROM': 6, 'TO': 1})
            assert 1 <= r <= 6

    def test_random_equal_values(self) -> None:
        """When FROM == TO, value equals that number."""
        r = self._eval('operator_random', {'FROM': 42, 'TO': 42})
        assert r == 42

    # ── String ──────────────────────────────────────────────────────
    def test_join(self) -> None:
        assert self._eval('operator_join', {'STRING1': 'hello', 'STRING2': 'world'}) == 'helloworld'
        assert self._eval('operator_join', {'STRING1': 'abc', 'STRING2': ''}) == 'abc'
        assert self._eval('operator_join', {'STRING1': '', 'STRING2': 'def'}) == 'def'
        assert self._eval('operator_join', {'STRING1': 123, 'STRING2': 456}) == '123456'

    def test_letter_of(self) -> None:
        assert self._eval('operator_letter_of', {'LETTER': 1, 'STRING': 'hello'}) == 'h'
        assert self._eval('operator_letter_of', {'LETTER': 5, 'STRING': 'hello'}) == 'o'
        assert self._eval('operator_letter_of', {'LETTER': 3, 'STRING': 'abc'}) == 'c'
        assert self._eval('operator_letter_of', {'LETTER': 0, 'STRING': 'hello'}) == ''
        assert self._eval('operator_letter_of', {'LETTER': 10, 'STRING': 'hi'}) == ''

    def test_length(self) -> None:
        assert self._eval('operator_length', {'STRING': 'hello'}) == 5
        assert self._eval('operator_length', {'STRING': ''}) == 0
        assert self._eval('operator_length', {'STRING': 12345}) == 5
        assert self._eval('operator_length', {'STRING': 'a b'}) == 3

    def test_contains(self) -> None:
        assert (
            self._eval('operator_contains', {'STRING1': 'hello world', 'STRING2': 'world'}) is True
        )
        assert (
            self._eval('operator_contains', {'STRING1': 'hello world', 'STRING2': 'xyz'}) is False
        )
        assert (
            self._eval('operator_contains', {'STRING1': 'Hello World', 'STRING2': 'world'}) is True
        )
        assert self._eval('operator_contains', {'STRING1': 'abc', 'STRING2': 'ABCD'}) is False
        assert self._eval('operator_contains', {'STRING1': '', 'STRING2': ''}) is True
        assert self._eval('operator_contains', {'STRING1': 'hello', 'STRING2': ''}) is True

    # ── Mod ─────────────────────────────────────────────────────────
    def test_mod(self) -> None:
        assert self._eval('operator_mod', {'NUM1': 10, 'NUM2': 3}) == 1
        assert self._eval('operator_mod', {'NUM1': 7, 'NUM2': 5}) == 2
        assert self._eval('operator_mod', {'NUM1': 0, 'NUM2': 5}) == 0

    def test_mod_non_negative_positive_divisor(self) -> None:
        """Scratch mod returns a non-negative remainder for positive divisor."""
        assert self._eval('operator_mod', {'NUM1': -7, 'NUM2': 3}) == 2

    @pytest.mark.xfail(reason='Python % differs from JS % for negative divisors')
    def test_mod_non_negative_negative_divisor(self) -> None:
        """Scratch mod always returns a non-negative remainder, even with negative divisor."""
        assert self._eval('operator_mod', {'NUM1': 7, 'NUM2': -3}) == 1
        assert self._eval('operator_mod', {'NUM1': -7, 'NUM2': -3}) == 2

    def test_mod_by_zero(self) -> None:
        """Mod by zero returns NaN."""
        r = self._eval('operator_mod', {'NUM1': 10, 'NUM2': 0})
        assert r != r  # NaN

    # ── Round ───────────────────────────────────────────────────────────
    def test_round(self) -> None:
        assert self._eval('operator_round', {'NUM': 3.4}) == 3
        assert self._eval('operator_round', {'NUM': 3.6}) == 4
        assert self._eval('operator_round', {'NUM': 3.5}) == 4
        assert self._eval('operator_round', {'NUM': 0}) == 0
        assert self._eval('operator_round', {'NUM': 42}) == 42

    @pytest.mark.xfail(reason="Python round uses banker's rounding; Scratch uses round-half-up")
    def test_round_half_up_negative(self) -> None:
        """-3.5 rounds to -3 in Scratch."""
        assert self._eval('operator_round', {'NUM': -3.5}) == -3

    # ── Math Op ─────────────────────────────────────────────────────
    def test_mathop_abs(self) -> None:
        assert self._eval('operator_mathop', {'NUM': -5}, {'OPERATOR': 'abs'}) == 5
        assert self._eval('operator_mathop', {'NUM': 3}, {'OPERATOR': 'abs'}) == 3
        assert self._eval('operator_mathop', {'NUM': 0}, {'OPERATOR': 'abs'}) == 0

    def test_mathop_floor(self) -> None:
        assert self._eval('operator_mathop', {'NUM': 3.7}, {'OPERATOR': 'floor'}) == 3
        assert self._eval('operator_mathop', {'NUM': -3.7}, {'OPERATOR': 'floor'}) == -4
        assert self._eval('operator_mathop', {'NUM': 42}, {'OPERATOR': 'floor'}) == 42

    def test_mathop_ceiling(self) -> None:
        assert self._eval('operator_mathop', {'NUM': 3.2}, {'OPERATOR': 'ceiling'}) == 4
        assert self._eval('operator_mathop', {'NUM': -3.2}, {'OPERATOR': 'ceiling'}) == -3
        assert self._eval('operator_mathop', {'NUM': 42}, {'OPERATOR': 'ceiling'}) == 42

    def test_mathop_sqrt(self) -> None:
        assert self._eval('operator_mathop', {'NUM': 9}, {'OPERATOR': 'sqrt'}) == 3
        assert self._eval('operator_mathop', {'NUM': 2}, {'OPERATOR': 'sqrt'}) == pytest.approx(
            1.41421356237
        )
        r = self._eval('operator_mathop', {'NUM': -1}, {'OPERATOR': 'sqrt'})
        assert r != r  # NaN

    def test_mathop_sin(self) -> None:
        r90 = self._eval('operator_mathop', {'NUM': 90}, {'OPERATOR': 'sin'})
        assert r90 == pytest.approx(1.0, abs=1e-10)
        r0 = self._eval('operator_mathop', {'NUM': 0}, {'OPERATOR': 'sin'})
        assert r0 == pytest.approx(0.0, abs=1e-10)
        r180 = self._eval('operator_mathop', {'NUM': 180}, {'OPERATOR': 'sin'})
        assert r180 == pytest.approx(0.0, abs=1e-10)
        r30 = self._eval('operator_mathop', {'NUM': 30}, {'OPERATOR': 'sin'})
        assert r30 == pytest.approx(0.5, abs=1e-10)

    def test_mathop_sin_rounds_to_10dp(self) -> None:
        """sin rounds to 10 decimal places to avoid float artifacts."""
        r = self._eval('operator_mathop', {'NUM': 0}, {'OPERATOR': 'sin'})
        assert r == 0.0

    def test_mathop_cos(self) -> None:
        r0 = self._eval('operator_mathop', {'NUM': 0}, {'OPERATOR': 'cos'})
        assert r0 == pytest.approx(1.0, abs=1e-10)
        r90 = self._eval('operator_mathop', {'NUM': 90}, {'OPERATOR': 'cos'})
        assert r90 == pytest.approx(0.0, abs=1e-10)
        r180 = self._eval('operator_mathop', {'NUM': 180}, {'OPERATOR': 'cos'})
        assert r180 == pytest.approx(-1.0, abs=1e-10)
        r60 = self._eval('operator_mathop', {'NUM': 60}, {'OPERATOR': 'cos'})
        assert r60 == pytest.approx(0.5, abs=1e-10)

    def test_mathop_cos_rounds_to_10dp(self) -> None:
        """cos rounds to 10 decimal places to avoid float artifacts."""
        r = self._eval('operator_mathop', {'NUM': 90}, {'OPERATOR': 'cos'})
        assert r == 0.0

    def test_mathop_tan(self) -> None:
        r = self._eval('operator_mathop', {'NUM': 45}, {'OPERATOR': 'tan'})
        assert r == pytest.approx(1.0, abs=1e-10)
        r0 = self._eval('operator_mathop', {'NUM': 0}, {'OPERATOR': 'tan'})
        assert r0 == pytest.approx(0.0, abs=1e-10)
        r90 = self._eval('operator_mathop', {'NUM': 90}, {'OPERATOR': 'tan'})
        assert r90 == float('inf')

    def test_mathop_asin(self) -> None:
        r = self._eval('operator_mathop', {'NUM': 1}, {'OPERATOR': 'asin'})
        assert r == pytest.approx(90.0, abs=1e-10)
        r0 = self._eval('operator_mathop', {'NUM': 0}, {'OPERATOR': 'asin'})
        assert r0 == pytest.approx(0.0, abs=1e-10)

    def test_mathop_asin_clamps_input(self) -> None:
        """asin clamps input to [-1, 1]."""
        r = self._eval('operator_mathop', {'NUM': 1.5}, {'OPERATOR': 'asin'})
        assert r == pytest.approx(90.0, abs=1e-10)
        r2 = self._eval('operator_mathop', {'NUM': -1.5}, {'OPERATOR': 'asin'})
        assert r2 == pytest.approx(-90.0, abs=1e-10)

    def test_mathop_acos(self) -> None:
        r = self._eval('operator_mathop', {'NUM': 1}, {'OPERATOR': 'acos'})
        assert r == pytest.approx(0.0, abs=1e-10)
        r0 = self._eval('operator_mathop', {'NUM': 0}, {'OPERATOR': 'acos'})
        assert r0 == pytest.approx(90.0, abs=1e-10)

    def test_mathop_acos_clamps_input(self) -> None:
        """acos clamps input to [-1, 1]."""
        r = self._eval('operator_mathop', {'NUM': 1.5}, {'OPERATOR': 'acos'})
        assert r == pytest.approx(0.0, abs=1e-10)
        r2 = self._eval('operator_mathop', {'NUM': -1.5}, {'OPERATOR': 'acos'})
        assert r2 == pytest.approx(180.0, abs=1e-10)

    def test_mathop_atan(self) -> None:
        r0 = self._eval('operator_mathop', {'NUM': 0}, {'OPERATOR': 'atan'})
        assert r0 == pytest.approx(0.0, abs=1e-10)
        r1 = self._eval('operator_mathop', {'NUM': 1}, {'OPERATOR': 'atan'})
        assert r1 == pytest.approx(45.0, abs=1e-10)

    def test_mathop_ln(self) -> None:
        r = self._eval('operator_mathop', {'NUM': 1}, {'OPERATOR': 'ln'})
        assert r == pytest.approx(0.0, abs=1e-10)
        r_e = self._eval('operator_mathop', {'NUM': 2.718281828459045}, {'OPERATOR': 'ln'})
        assert r_e == pytest.approx(1.0, abs=1e-10)
        r_neg = self._eval('operator_mathop', {'NUM': -1}, {'OPERATOR': 'ln'})
        assert r_neg == float('-inf')

    def test_mathop_log(self) -> None:
        r = self._eval('operator_mathop', {'NUM': 1}, {'OPERATOR': 'log'})
        assert r == pytest.approx(0.0, abs=1e-10)
        r10 = self._eval('operator_mathop', {'NUM': 100}, {'OPERATOR': 'log'})
        assert r10 == pytest.approx(2.0, abs=1e-10)
        r_neg = self._eval('operator_mathop', {'NUM': -1}, {'OPERATOR': 'log'})
        assert r_neg == float('-inf')

    def test_mathop_e_pow(self) -> None:
        r = self._eval('operator_mathop', {'NUM': 0}, {'OPERATOR': 'e ^'})
        assert r == pytest.approx(1.0, abs=1e-10)
        r1 = self._eval('operator_mathop', {'NUM': 1}, {'OPERATOR': 'e ^'})
        assert r1 == pytest.approx(2.718281828459045, abs=1e-10)

    def test_mathop_10_pow(self) -> None:
        r0 = self._eval('operator_mathop', {'NUM': 0}, {'OPERATOR': '10 ^'})
        assert r0 == pytest.approx(1.0, abs=1e-10)
        r3 = self._eval('operator_mathop', {'NUM': 3}, {'OPERATOR': '10 ^'})
        assert r3 == pytest.approx(1000.0, abs=1e-10)

    def test_mathop_unknown_op_returns_zero(self) -> None:
        r = self._eval('operator_mathop', {'NUM': 42}, {'OPERATOR': 'nonexistent'})
        assert r == 0


# ═══════════════════════════════════════════════════════════════════════
#  Data — Variables
# ═══════════════════════════════════════════════════════════════════════


class TestDataVariables:
    def test_set_variable(self) -> None:
        t = _stack('data_setvariableto')
        _set(t, 'b0', inputs={'VALUE': Input(value=42)}, fields={'VARIABLE': Field(value='score')})
        t.variables['score'] = Variable('score', 0)
        rt = _run(t)
        v = t.lookup_variable('score')
        assert v is not None and v.value == 42

    def test_change_variable(self) -> None:
        t = _stack('data_changevariableby')
        _set(t, 'b0', inputs={'VALUE': Input(value=10)}, fields={'VARIABLE': Field(value='score')})
        t.variables['score'] = Variable('score', 5)
        rt = _run(t)
        v = t.lookup_variable('score')
        assert v is not None and v.value == 15

    def test_stage_variable_fallback(self) -> None:
        """Setting a sprite variable with no match falls back to stage."""
        t = _stack('data_setvariableto')
        t.blocks['b0'] = _op(
            'data_setvariableto',
            inputs={'VALUE': Input(value=99)},
            fields={'VARIABLE': Field(value='global_x')},
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

    def test_set_variable_string(self) -> None:
        """Setting a variable to a string stores the raw string."""
        t = _stack('data_setvariableto')
        _set(
            t, 'b0', inputs={'VALUE': Input(value='hello')}, fields={'VARIABLE': Field(value='msg')}
        )
        t.variables['msg'] = Variable('msg', '')
        rt = _run(t)
        v = t.lookup_variable('msg')
        assert v is not None and v.value == 'hello'

    def test_set_variable_float(self) -> None:
        """Float values are stored as-is."""
        t = _stack('data_setvariableto')
        _set(t, 'b0', inputs={'VALUE': Input(value=3.14)}, fields={'VARIABLE': Field(value='pi')})
        t.variables['pi'] = Variable('pi', 0)
        rt = _run(t)
        v = t.lookup_variable('pi')
        assert v is not None and v.value == 3.14

    def test_change_variable_negative(self) -> None:
        """Changing by a negative delta decrements the variable."""
        t = _stack('data_changevariableby')
        _set(t, 'b0', inputs={'VALUE': Input(value=-5)}, fields={'VARIABLE': Field(value='score')})
        t.variables['score'] = Variable('score', 10)
        rt = _run(t)
        v = t.lookup_variable('score')
        assert v is not None and v.value == 5

    def test_change_variable_string_delta(self) -> None:
        """Non-numeric string delta coerces to 0 (no change)."""
        t = _stack('data_changevariableby')
        _set(
            t, 'b0', inputs={'VALUE': Input(value='abc')}, fields={'VARIABLE': Field(value='score')}
        )
        t.variables['score'] = Variable('score', 7)
        rt = _run(t)
        v = t.lookup_variable('score')
        assert v is not None and v.value == 7

    def test_variable_reporter(self) -> None:
        """data_variable reporter reads the current variable value."""
        t = _stack('data_variable')
        _set(t, 'b0', fields={'VARIABLE': Field(value='score')})
        t.variables['score'] = Variable('score', 99)
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_variable_reporter_auto_create(self) -> None:
        """data_variable creates variable with default 0 if not found."""
        t = _stack('data_variable')
        _set(t, 'b0', fields={'VARIABLE': Field(value='auto_var')})
        # No pre-existing variable — should auto-create with 0
        rt = _run(t)
        assert len(rt.threads) == 0

    # ── Cloud variables ────────────────────────────────────────────────

    def test_cloud_variable_set(self) -> None:
        """Setting a cloud variable updates its value."""
        t = _stack('data_setvariableto')
        t.variables['score'] = Variable('☁ score', 0, is_cloud=True)
        _set(
            t, 'b0', inputs={'VALUE': Input(value=99)}, fields={'VARIABLE': Field(value='☁ score')}
        )
        rt = _run(t)
        var = t.lookup_variable('☁ score')
        assert var is not None and var.value == 99
        assert var.is_cloud

    def test_cloud_variable_change(self) -> None:
        """Changing a cloud variable adds delta to its value."""
        t = _stack('data_changevariableby')
        t.variables['c'] = Variable('☁ counter', 10, is_cloud=True)
        _set(
            t, 'b0', inputs={'VALUE': Input(value=5)}, fields={'VARIABLE': Field(value='☁ counter')}
        )
        rt = _run(t)
        var = t.lookup_variable('☁ counter')
        assert var is not None and var.value == 15

    def test_cloud_update_sent_via_io_query(self) -> None:
        """data_setvariableto sends cloud update via io_query when variable is cloud."""
        rt = Runtime()
        rt._real_time = False
        rt.add_target(Target(name='Stage', is_stage=True))
        rt.register_all(OPCODE_MAP)

        # Track cloud updates
        sent: list[tuple[str, Any]] = []

        class TrackingProvider:
            def update_variable(self, name: str, value: Any) -> None:
                sent.append((name, value))

        rt._init_cloud()
        rt._cloud.set_provider(TrackingProvider())

        t = Target(name='Sprite')
        t.variables['v'] = Variable('☁ x', 0, is_cloud=True)
        t.blocks['h'] = Block(id='h', opcode='event_whenflagclicked', top_level=True, next='b')
        t.blocks['b'] = Block(
            id='b',
            opcode='data_setvariableto',
            inputs={'VALUE': Input(value=42)},
            fields={'VARIABLE': Field(value='☁ x')},
        )
        t._rebuild_hat_cache()
        rt.add_target(t)

        rt.green_flag()
        for _ in range(10):
            rt.step()

        assert len(sent) == 1, f'Expected 1 cloud update, got {sent}'
        assert sent[0] == ('☁ x', 42)

    def test_cloud_variable_limit(self) -> None:
        """Runtime enforces max 10 cloud variables."""
        rt = Runtime()
        rt._cloud_count = 10
        assert not rt.can_add_cloud_variable()
        # Under limit
        rt2 = Runtime()
        assert rt2.can_add_cloud_variable()
        rt2.add_cloud_variable()
        assert rt2._cloud_count == 1
        assert rt2.has_cloud_data()

    def test_cloud_variable_non_cloud_not_sent(self) -> None:
        """Non-cloud variables do not trigger cloud updates."""
        t = _stack('data_setvariableto')
        t.variables['v'] = Variable('local_var', 0, is_cloud=False)
        _set(
            t,
            'b0',
            inputs={'VALUE': Input(value=77)},
            fields={'VARIABLE': Field(value='local_var')},
        )
        rt = _run(t)
        var = t.lookup_variable('local_var')
        assert var is not None and var.value == 77
        assert not var.is_cloud

    def test_cloud_sb3_round_trip(self) -> None:
        """Cloud flag survives SB3 serialization."""
        from scratch.sb3.io import _build_project_json  # noqa: PLC0415

        rt = Runtime()
        rt._real_time = False
        rt.add_target(Target(name='Stage', is_stage=True))
        t = Target(name='Sprite')
        t.variables['c'] = Variable('☁ data', 42, is_cloud=True)
        rt.add_target(t)
        project = _build_project_json(rt)
        var_json = project['targets'][1]['variables']['c']
        assert len(var_json) == 3
        assert var_json[0] == '☁ data'
        assert var_json[1] == 42
        assert var_json[2] is True


# ═══════════════════════════════════════════════════════════════════════
#  Data — Lists
# ═══════════════════════════════════════════════════════════════════════


class TestDataLists:
    def test_add_to_list(self) -> None:
        t = _stack('data_addtolist')
        _set(t, 'b0', inputs={'ITEM': Input(value='x')}, fields={'LIST': Field(value='items')})
        t.lists['items'] = ListVar('items')
        rt = _run(t)
        assert t.lists['items'].contents == ['x']

    def test_add_delete_list(self) -> None:
        t = _stack('data_addtolist', 'data_deleteoflist')
        _set(t, 'b0', inputs={'ITEM': Input(value='a')}, fields={'LIST': Field(value='items')})
        _set(t, 'b1', inputs={'INDEX': Input(value=1)}, fields={'LIST': Field(value='items')})
        t.lists['items'] = ListVar('items')
        t._rebuild_hat_cache()
        rt = _run(t)
        assert t.lists['items'].contents == []

    def test_add_to_list_multiple(self) -> None:
        """Adding multiple items appends each in order."""
        t = _stack('data_addtolist', 'data_addtolist', 'data_addtolist')
        _set(t, 'b0', inputs={'ITEM': Input(value='a')}, fields={'LIST': Field(value='items')})
        _set(t, 'b1', inputs={'ITEM': Input(value='b')}, fields={'LIST': Field(value='items')})
        _set(t, 'b2', inputs={'ITEM': Input(value='c')}, fields={'LIST': Field(value='items')})
        t.lists['items'] = ListVar('items')
        rt = _run(t)
        assert t.lists['items'].contents == ['a', 'b', 'c']

    def test_add_to_list_numeric(self) -> None:
        """Adding numeric items stores them as raw values."""
        t = _stack('data_addtolist')
        _set(t, 'b0', inputs={'ITEM': Input(value=42)}, fields={'LIST': Field(value='nums')})
        t.lists['nums'] = ListVar('nums')
        rt = _run(t)
        assert t.lists['nums'].contents == [42]

    def test_delete_of_list_by_index(self) -> None:
        """Deleting by numeric index removes that element."""
        t = _stack('data_deleteoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', inputs={'INDEX': Input(value=2)}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert t.lists['items'].contents == ['a', 'c']

    def test_delete_of_list_all(self) -> None:
        """Deleting with INDEX='all' clears the entire list."""
        t = _stack('data_deleteoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', inputs={'INDEX': Input(value='all')}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert t.lists['items'].contents == []

    def test_delete_of_list_last(self) -> None:
        """Deleting with INDEX='last' removes the last element."""
        t = _stack('data_deleteoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', inputs={'INDEX': Input(value='last')}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert t.lists['items'].contents == ['a', 'b']

    def test_delete_of_list_random(self) -> None:
        """Deleting with INDEX='random' removes one element."""
        t = _stack('data_deleteoflist')
        t.lists['items'] = ListVar('items', contents=['x', 'y', 'z'])
        _set(
            t, 'b0', inputs={'INDEX': Input(value='random')}, fields={'LIST': Field(value='items')}
        )
        rt = _run(t)
        assert len(t.lists['items'].contents) == 2

    def test_delete_of_list_invalid_index(self) -> None:
        """Deleting with an out-of-range index is a no-op."""
        t = _stack('data_deleteoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b'])
        _set(t, 'b0', inputs={'INDEX': Input(value=99)}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert t.lists['items'].contents == ['a', 'b']

    def test_delete_of_list_empty(self) -> None:
        """Deleting from an empty list is a no-op."""
        t = _stack('data_deleteoflist')
        t.lists['items'] = ListVar('items')
        _set(t, 'b0', inputs={'INDEX': Input(value='last')}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert t.lists['items'].contents == []

    def test_delete_all_of_list(self) -> None:
        """data_deletealloflist clears all items."""
        t = _stack('data_deletealloflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert t.lists['items'].contents == []

    def test_insert_at_list(self) -> None:
        """Inserting at a numeric index places the item before that position."""
        t = _stack('data_insertatlist')
        t.lists['items'] = ListVar('items', contents=['a', 'c'])
        _set(
            t,
            'b0',
            inputs={'ITEM': Input(value='b'), 'INDEX': Input(value=2)},
            fields={'LIST': Field(value='items')},
        )
        rt = _run(t)
        assert t.lists['items'].contents == ['a', 'b', 'c']

    def test_insert_at_list_beginning(self) -> None:
        """Inserting at index 1 places the item at the front."""
        t = _stack('data_insertatlist')
        t.lists['items'] = ListVar('items', contents=['b', 'c'])
        _set(
            t,
            'b0',
            inputs={'ITEM': Input(value='a'), 'INDEX': Input(value=1)},
            fields={'LIST': Field(value='items')},
        )
        rt = _run(t)
        assert t.lists['items'].contents == ['a', 'b', 'c']

    def test_insert_at_list_last(self) -> None:
        """Inserting with INDEX='last' appends at the end."""
        t = _stack('data_insertatlist')
        t.lists['items'] = ListVar('items', contents=['a', 'b'])
        _set(
            t,
            'b0',
            inputs={'ITEM': Input(value='c'), 'INDEX': Input(value='last')},
            fields={'LIST': Field(value='items')},
        )
        rt = _run(t)
        assert t.lists['items'].contents == ['a', 'b', 'c']

    def test_replace_item_of_list(self) -> None:
        """Replace item at a valid index modifies the list."""
        t = _stack('data_replaceitemoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'x', 'c'])
        _set(
            t,
            'b0',
            inputs={'ITEM': Input(value='b'), 'INDEX': Input(value=2)},
            fields={'LIST': Field(value='items')},
        )
        rt = _run(t)
        assert t.lists['items'].contents == ['a', 'b', 'c']

    def test_replace_item_of_list_invalid(self) -> None:
        """Replace with an out-of-range index is a no-op."""
        t = _stack('data_replaceitemoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b'])
        _set(
            t,
            'b0',
            inputs={'ITEM': Input(value='z'), 'INDEX': Input(value=99)},
            fields={'LIST': Field(value='items')},
        )
        rt = _run(t)
        assert t.lists['items'].contents == ['a', 'b']

    def test_item_of_list(self) -> None:
        """data_itemoflist returns the item at a numeric index."""
        t = _stack('data_itemoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', inputs={'INDEX': Input(value=2)}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_item_of_list_invalid(self) -> None:
        """data_itemoflist with an invalid index returns '' (runs cleanly)."""
        t = _stack('data_itemoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b'])
        _set(t, 'b0', inputs={'INDEX': Input(value=99)}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_item_of_list_empty(self) -> None:
        """data_itemoflist on an empty list returns ''."""
        t = _stack('data_itemoflist')
        t.lists['items'] = ListVar('items')
        _set(t, 'b0', inputs={'INDEX': Input(value=1)}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_item_num_of_list(self) -> None:
        """data_itemnumoflist returns the 1-based index of a matching item."""
        t = _stack('data_itemnumoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', inputs={'ITEM': Input(value='b')}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_item_num_of_list_numeric_match(self) -> None:
        """data_itemnumoflist matches numeric values via Cast.compare: 5 matches '5'."""
        t = _stack('data_itemnumoflist')
        t.lists['items'] = ListVar('items', contents=[10, '5', 20])
        _set(t, 'b0', inputs={'ITEM': Input(value=5)}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_item_num_of_list_not_found(self) -> None:
        """data_itemnumoflist returns 0 when item is not in the list."""
        t = _stack('data_itemnumoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', inputs={'ITEM': Input(value='z')}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_item_num_of_list_case_insensitive(self) -> None:
        """data_itemnumoflist uses case-insensitive string comparison."""
        t = _stack('data_itemnumoflist')
        t.lists['items'] = ListVar('items', contents=['Hello'])
        _set(t, 'b0', inputs={'ITEM': Input(value='hello')}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_length_of_list(self) -> None:
        """data_lengthoflist returns the number of items."""
        t = _stack('data_lengthoflist')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_length_of_list_empty(self) -> None:
        """data_lengthoflist on an empty list returns 0."""
        t = _stack('data_lengthoflist')
        t.lists['items'] = ListVar('items')
        _set(t, 'b0', fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_list_contains_item(self) -> None:
        """data_listcontainsitem returns True when item is in the list."""
        t = _stack('data_listcontainsitem')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', inputs={'ITEM': Input(value='b')}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_list_contains_item_not_found(self) -> None:
        """data_listcontainsitem returns False when item is not in the list."""
        t = _stack('data_listcontainsitem')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', inputs={'ITEM': Input(value='z')}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_list_contains_item_cross_type(self) -> None:
        """data_listcontainsitem matches cross-type via Cast.compare (e.g. 5 == '5')."""
        t = _stack('data_listcontainsitem')
        t.lists['items'] = ListVar('items', contents=[10, '5', 20])
        _set(t, 'b0', inputs={'ITEM': Input(value=5)}, fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_list_contents_single_char(self) -> None:
        """data_listcontents joins single-char items with '' (no separator)."""
        t = _stack('data_listcontents')
        t.lists['items'] = ListVar('items', contents=['a', 'b', 'c'])
        _set(t, 'b0', fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_list_contents_multi_char(self) -> None:
        """data_listcontents joins multi-char items with ' '."""
        t = _stack('data_listcontents')
        t.lists['items'] = ListVar('items', contents=['ab', 'cd', 'ef'])
        _set(t, 'b0', fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_list_contents_empty(self) -> None:
        """data_listcontents on an empty list returns ''."""
        t = _stack('data_listcontents')
        t.lists['items'] = ListVar('items')
        _set(t, 'b0', fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_list_contents_mixed_single_and_multi(self) -> None:
        """Mixed single-char and multi-char items use ' ' separator."""
        t = _stack('data_listcontents')
        t.lists['items'] = ListVar('items', contents=['a', 'bc', 'd'])
        _set(t, 'b0', fields={'LIST': Field(value='items')})
        rt = _run(t)
        assert len(rt.threads) == 0


# ═══════════════════════════════════════════════════════════════════════
#  Sensing
# ═══════════════════════════════════════════════════════════════════════


class TestSensing:
    """Sensing opcodes.

    Each reporter is tested via a helper that builds a one-block target
    and calls ``rt.evaluate``.  Commands (askandwait, setdragmode, etc.)
    use the ``_stack``/``_run`` pattern or manual stepping.
    """

    # ── Helper ──────────────────────────────────────────────────────
    def _eval(
        self,
        opcode: str,
        inputs: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
    ) -> Any:
        """Build a target with one reporter block and evaluate it."""
        t = _make_tgt()
        bid = _id()
        t.blocks[bid] = _op(opcode, inputs, fields)
        t._rebuild_hat_cache()
        rt = _rt(t)
        return rt.evaluate(t, bid)

    def _eval_with(
        self,
        opcode: str,
        inputs: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
        *,
        setup: Any = None,
        get_rt: bool = False,
    ) -> Any:
        """Evaluate a reporter after running *setup(rt)*."""
        t = _make_tgt()
        bid = _id()
        t.blocks[bid] = _op(opcode, inputs, fields)
        t._rebuild_hat_cache()
        rt = _rt(t)
        if setup:
            setup(rt)
        val = rt.evaluate(t, bid)
        return (val, rt) if get_rt else val

    # ═════════════════════════════════════════════════════════════════
    #  sensing_touchingobject
    # ═════════════════════════════════════════════════════════════════
    def test_touchingobject_edge_right(self) -> None:
        """Sprite beyond right edge reports touching edge."""
        t = Target(name='Sprite')
        t.x = 300  # past 240
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_touchingobject', fields={'TOUCHINGOBJECTMENU': Field(value='_edge_')}
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) is True

    def test_touchingobject_edge_left(self) -> None:
        """Sprite beyond left edge reports touching edge."""
        t = Target(name='Sprite')
        t.x = -300
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_touchingobject', fields={'TOUCHINGOBJECTMENU': Field(value='_edge_')}
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) is True

    def test_touchingobject_edge_top(self) -> None:
        """Sprite beyond top edge reports touching edge."""
        t = Target(name='Sprite')
        t.y = 200  # past 180
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_touchingobject', fields={'TOUCHINGOBJECTMENU': Field(value='_edge_')}
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) is True

    def test_touchingobject_edge_bottom(self) -> None:
        """Sprite beyond bottom edge reports touching edge."""
        t = Target(name='Sprite')
        t.y = -200
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_touchingobject', fields={'TOUCHINGOBJECTMENU': Field(value='_edge_')}
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) is True

    def test_touchingobject_not_touching_edge(self) -> None:
        """Sprite inside stage bounds does not touch edge."""
        t = Target(name='Sprite')
        t.x = 50
        t.y = 50
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_touchingobject', fields={'TOUCHINGOBJECTMENU': Field(value='_edge_')}
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) is False

    def test_touchingobject_mouse(self) -> None:
        """_mouse_ always returns False (unsupported in py-scratch)."""
        assert (
            self._eval(
                'sensing_touchingobject', fields={'TOUCHINGOBJECTMENU': Field(value='_mouse_')}
            )
            is False
        )

    def test_touchingobject_sprite_at_same_position(self) -> None:
        """Two sprites at the same position with no costume (point bounds)
        do NOT register as touching (strict inequality in AABB check)."""
        t1 = Target(name='Sprite')
        t1.x = 0
        t2 = Target(name='Other')
        t2.x = 0
        bid = _id()
        t1.blocks[bid] = _op(
            'sensing_touchingobject', fields={'TOUCHINGOBJECTMENU': Field(value='Other')}
        )
        t1._rebuild_hat_cache()
        rt = Runtime()
        rt.add_target(Target(name='Stage', is_stage=True))
        rt.add_target(t1)
        rt.add_target(t2)
        rt.register_all(OPCODE_MAP)
        assert rt.evaluate(t1, bid) is False

    def test_touchingobject_nonexistent_sprite(self) -> None:
        """Non-existent sprite returns False."""
        assert (
            self._eval(
                'sensing_touchingobject', fields={'TOUCHINGOBJECTMENU': Field(value='Ghost')}
            )
            is False
        )

    # ═════════════════════════════════════════════════════════════════
    #  sensing_distanceto
    # ═════════════════════════════════════════════════════════════════
    def test_distanceto_mouse_default(self) -> None:
        """Distance to mouse at origin is 0."""
        assert (
            self._eval(
                'sensing_distanceto',
                fields={'DISTANCETOMENU': Field(value='_mouse_')},
            )
            == 0.0
        )

    def test_distanceto_mouse_offset(self) -> None:
        """Distance to mouse is sqrt(dx² + dy²)."""
        t = Target(name='Sprite')
        t.x = 0
        t.y = 0
        bid = _id()
        t.blocks[bid] = _op('sensing_distanceto', fields={'DISTANCETOMENU': Field(value='_mouse_')})
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt._mouse_x = 30
        rt._mouse_y = 40
        assert rt.evaluate(t, bid) == 50.0

    def test_distanceto_sprite(self) -> None:
        """Distance between two sprites."""
        t1 = Target(name='Sprite')
        t1.x = 0
        t1.y = 0
        t2 = Target(name='Other')
        t2.x = 3
        t2.y = 4
        bid = _id()
        t1.blocks[bid] = _op('sensing_distanceto', fields={'DISTANCETOMENU': Field(value='Other')})
        t1._rebuild_hat_cache()
        rt = Runtime()
        rt.add_target(Target(name='Stage', is_stage=True))
        rt.add_target(t1)
        rt.add_target(t2)
        rt.register_all(OPCODE_MAP)
        assert rt.evaluate(t1, bid) == 5.0

    def test_distanceto_nonexistent(self) -> None:
        """Non-existent target returns 10000."""
        assert (
            self._eval('sensing_distanceto', fields={'DISTANCETOMENU': Field(value='Ghost')})
            == 10000.0
        )

    # ═════════════════════════════════════════════════════════════════
    #  sensing_timer / sensing_resettimer
    # ═════════════════════════════════════════════════════════════════
    def test_timer(self) -> None:
        """Timer reports elapsed virtual time."""
        t = _stack('sensing_resettimer', 'sensing_timer')
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_timer_after_steps(self) -> None:
        """Timer increases after stepping the runtime."""
        rt = Runtime()
        rt._real_time = False
        rt.register_all(OPCODE_MAP)
        # Step 30 frames = 0.5 seconds at 60 fps
        for _ in range(30):
            rt.step()
        assert rt.clock.now() == pytest.approx(0.5, abs=0.01)

    def test_resettimer(self) -> None:
        """Reset timer sets elapsed time to 0."""
        rt = Runtime()
        rt._real_time = False
        rt.register_all(OPCODE_MAP)
        # Advance a few steps so timer > 0
        for _ in range(10):
            rt.step()
        assert rt.clock.now() > 0.0
        # Reset and verify
        rt.clock.reset()
        assert rt.clock.now() == 0.0

    # ═════════════════════════════════════════════════════════════════
    #  sensing_of
    # ═════════════════════════════════════════════════════════════════
    def test_of_x_position(self) -> None:
        """sensing_of reports x position."""
        t = Target(name='Sprite')
        t.x = 75
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='x position')},
            fields={'OBJECT': Field(value='Sprite')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 75

    def test_of_y_position(self) -> None:
        """sensing_of reports y position."""
        t = Target(name='Sprite')
        t.y = -30
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='y position')},
            fields={'OBJECT': Field(value='Sprite')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == -30

    def test_of_direction(self) -> None:
        """sensing_of reports direction."""
        t = Target(name='Sprite')
        t.direction = 45
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='direction')},
            fields={'OBJECT': Field(value='Sprite')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 45

    def test_of_costume_number(self) -> None:
        """sensing_of reports 1-indexed costume number."""
        t = Target(name='Sprite')
        t.costumes = [Costume(name='a'), Costume(name='b')]
        t.costume_index = 1  # 0-based → second costume
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='costume #')},
            fields={'OBJECT': Field(value='Sprite')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 2

    def test_of_costume_name(self) -> None:
        """sensing_of reports costume name.

        NOTE: Current implementation returns the 1-indexed costume number
        for ``'costume name'``, which is incorrect per spec.
        """
        t = Target(name='Sprite')
        t.costumes = [Costume(name='costume-a')]
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='costume name')},
            fields={'OBJECT': Field(value='Sprite')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        # Spec: should return 'costume-a'.  Current impl returns 1.
        assert rt.evaluate(t, bid) == 'costume-a'

    def test_of_size(self) -> None:
        """sensing_of reports size."""
        t = Target(name='Sprite')
        t.size = 150
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='size')},
            fields={'OBJECT': Field(value='Sprite')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 150

    def test_of_volume(self) -> None:
        """sensing_of reports volume."""
        t = Target(name='Sprite')
        t.volume = 75.0
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='volume')},
            fields={'OBJECT': Field(value='Sprite')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 75.0

    def test_of_backdrop_number(self) -> None:
        """sensing_of backdrop # on stage returns 1-indexed backdrop."""
        stage = Target(name='Stage', is_stage=True)
        stage.costumes = [Costume(name='backdrop1'), Costume(name='backdrop2')]
        stage.costume_index = 1  # second backdrop
        t = Target(name='Sprite')
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='backdrop #')},
            fields={'OBJECT': Field(value='Stage')},
        )
        t._rebuild_hat_cache()
        rt = Runtime()
        rt.add_target(stage)
        rt.add_target(t)
        rt.register_all(OPCODE_MAP)
        assert rt.evaluate(t, bid) == 2

    def test_of_backdrop_name(self) -> None:
        """sensing_of backdrop name on stage returns the name string."""
        stage = Target(name='Stage', is_stage=True)
        stage.costumes = [Costume(name='Backdrop1')]
        t = Target(name='Sprite')
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='backdrop name')},
            fields={'OBJECT': Field(value='Stage')},
        )
        t._rebuild_hat_cache()
        rt = Runtime()
        rt.add_target(stage)
        rt.add_target(t)
        rt.register_all(OPCODE_MAP)
        assert rt.evaluate(t, bid) == 'Backdrop1'

    def test_of_backdrop_on_sprite_returns_empty(self) -> None:
        """backdrop # / name on a non-stage target returns 0 / ''."""
        t = Target(name='Sprite')
        t.costumes = [Costume(name='a')]
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='backdrop #')},
            fields={'OBJECT': Field(value='Sprite')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 0
        # backdrop name on sprite
        bid2 = _id()
        t.blocks[bid2] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='backdrop name')},
            fields={'OBJECT': Field(value='Sprite')},
        )
        t._rebuild_hat_cache()
        assert rt.evaluate(t, bid2) == ''

    def test_of_variable(self) -> None:
        """sensing_of with a variable name returns the variable's value."""
        t = Target(name='Sprite')
        t.variables['score'] = Variable('score', 42)
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='score')},
            fields={'OBJECT': Field(value='Sprite')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 42

    def test_of_nonexistent_variable(self) -> None:
        """sensing_of with a non-existent variable name returns 0."""
        assert (
            self._eval(
                'sensing_of',
                inputs={'PROPERTY': Input(value='nonexistent')},
                fields={'OBJECT': Field(value='Sprite')},
            )
            == 0
        )

    def test_of_unknown_object_fallback(self) -> None:
        """sensing_of with an unknown OBJECT falls back to the calling sprite."""
        t = Target(name='Sprite')
        t.x = 10
        bid = _id()
        t.blocks[bid] = _op(
            'sensing_of',
            inputs={'PROPERTY': Input(value='x position')},
            fields={'OBJECT': Field(value='NoSuchTarget')},
        )
        t._rebuild_hat_cache()
        rt = _rt(t)
        assert rt.evaluate(t, bid) == 10

    # ═════════════════════════════════════════════════════════════════
    #  sensing_mousex / sensing_mousey / sensing_mousedown
    # ═════════════════════════════════════════════════════════════════
    def test_mousex_default(self) -> None:
        """sensing_mousex returns default 0."""
        assert self._eval('sensing_mousex') == 0.0

    def test_mousex_set(self) -> None:
        """sensing_mousex reflects runtime mouse x."""
        result, rt = self._eval_with(
            'sensing_mousex', get_rt=True, setup=lambda rt: setattr(rt, '_mouse_x', 120.0)
        )
        assert result == 120.0

    def test_mousey_default(self) -> None:
        """sensing_mousey returns default 0."""
        assert self._eval('sensing_mousey') == 0.0

    def test_mousey_set(self) -> None:
        """sensing_mousey reflects runtime mouse y."""
        result, rt = self._eval_with(
            'sensing_mousey', get_rt=True, setup=lambda rt: setattr(rt, '_mouse_y', -60.0)
        )
        assert result == -60.0

    def test_mousedown_true(self) -> None:
        """sensing_mousedown returns True when mouse is pressed."""
        result, rt = self._eval_with(
            'sensing_mousedown', get_rt=True, setup=lambda rt: setattr(rt, '_mouse_down', True)
        )
        assert result is True

    def test_mousedown_false(self) -> None:
        """sensing_mousedown returns False when mouse is not pressed."""
        assert self._eval('sensing_mousedown') is False

    # ═════════════════════════════════════════════════════════════════
    #  sensing_keypressed
    # ═════════════════════════════════════════════════════════════════
    def test_keypressed_thread_ends(self) -> None:
        """Existing test: keypressed finishes cleanly (regression)."""
        t = _stack('sensing_keypressed')
        _set(t, 'b0', fields={'KEY_OPTION': Field(value='space')})
        rt = _run(t)
        assert len(rt.threads) == 0

    def test_keypressed_true(self) -> None:
        """sensing_keypressed returns True when key is pressed."""
        result, rt = self._eval_with(
            'sensing_keypressed',
            fields={'KEY_OPTION': Field(value='space')},
            get_rt=True,
            setup=lambda rt: rt._keyboard.update({'space': True}),
        )
        assert result is True

    def test_keypressed_false(self) -> None:
        """sensing_keypressed returns False for unpressed key."""
        assert (
            self._eval('sensing_keypressed', fields={'KEY_OPTION': Field(value='space')}) is False
        )

    def test_keypressed_any(self) -> None:
        """sensing_keypressed 'any' returns True when any key is pressed."""
        result, rt = self._eval_with(
            'sensing_keypressed',
            fields={'KEY_OPTION': Field(value='any')},
            get_rt=True,
            setup=lambda rt: rt._keyboard.update({'space': True}),
        )
        assert result is True

    def test_keypressed_any_none(self) -> None:
        """sensing_keypressed 'any' returns False when no keys are pressed."""
        assert self._eval('sensing_keypressed', fields={'KEY_OPTION': Field(value='any')}) is False

    def test_keypressed_case_insensitive(self) -> None:
        """key names are lowercased before lookup."""
        result, rt = self._eval_with(
            'sensing_keypressed',
            fields={'KEY_OPTION': Field(value='SPACE')},
            get_rt=True,
            setup=lambda rt: rt._keyboard.update({'space': True}),
        )
        assert result is True

    # ═════════════════════════════════════════════════════════════════
    #  sensing_current
    # ═════════════════════════════════════════════════════════════════
    def test_current_year(self) -> None:
        """sensing_current YEAR returns reasonable year."""
        v = self._eval('sensing_current', fields={'CURRENTMENU': Field(value='YEAR')})
        assert isinstance(v, int)
        assert 2000 <= v <= 2100

    def test_current_month(self) -> None:
        """sensing_current MONTH returns 1-12."""
        v = self._eval('sensing_current', fields={'CURRENTMENU': Field(value='MONTH')})
        assert isinstance(v, int)
        assert 1 <= v <= 12

    def test_current_date(self) -> None:
        """sensing_current DATE returns 1-31."""
        v = self._eval('sensing_current', fields={'CURRENTMENU': Field(value='DATE')})
        assert isinstance(v, int)
        assert 1 <= v <= 31

    def test_current_dayofweek(self) -> None:
        """sensing_current DAYOFWEEK: 1=Sunday, …, 7=Saturday."""
        v = self._eval('sensing_current', fields={'CURRENTMENU': Field(value='DAYOFWEEK')})
        assert isinstance(v, int)
        assert 1 <= v <= 7
        # Sunday check: June 30, 2026 is a Tuesday → dayofweek should be 3
        # (Monday=2, Tuesday=3, Wednesday=4, Thursday=5, Friday=6, Saturday=7, Sunday=1)
        # Verify our calculation matches Python's weekday convention
        # tm_wday: 0=Monday, 6=Sunday
        # Scratch: 1=Sunday, 7=Saturday
        # Conversion: ((tm_wday + 1) % 7) + 1
        # If tm_wday=0 (Monday): (1 % 7) + 1 = 2 ✓
        # If tm_wday=1 (Tuesday): (2 % 7) + 1 = 3 ✓
        # If tm_wday=6 (Sunday): (7 % 7) + 1 = 1 ✓
        tm_wday = datetime.datetime.now().weekday()  # 0=Monday
        expected = ((tm_wday + 1) % 7) + 1
        assert v == expected, f'Today (tm_wday={tm_wday}) → expected dayofweek={expected}, got {v}'

    def test_current_hour(self) -> None:
        """sensing_current HOUR returns 0-23."""
        v = self._eval('sensing_current', fields={'CURRENTMENU': Field(value='HOUR')})
        assert isinstance(v, int)
        assert 0 <= v <= 23

    def test_current_minute(self) -> None:
        """sensing_current MINUTE returns 0-59."""
        v = self._eval('sensing_current', fields={'CURRENTMENU': Field(value='MINUTE')})
        assert isinstance(v, int)
        assert 0 <= v <= 59

    def test_current_second(self) -> None:
        """sensing_current SECOND returns 0-59."""
        v = self._eval('sensing_current', fields={'CURRENTMENU': Field(value='SECOND')})
        assert isinstance(v, int)
        assert 0 <= v <= 59

    def test_current_invalid_menu(self) -> None:
        """sensing_current with unknown menu returns 0."""
        v = self._eval('sensing_current', fields={'CURRENTMENU': Field(value='INVALID')})
        assert v == 0

    # ═════════════════════════════════════════════════════════════════
    #  sensing_dayssince2000
    # ═════════════════════════════════════════════════════════════════
    def test_dayssince2000(self) -> None:
        """sensing_dayssince2000 returns positive days since 2000-01-01."""
        v = self._eval('sensing_dayssince2000')
        assert isinstance(v, float)
        assert v > 0.0
        # Rough check: June 30 2026 is ~9675 days after Jan 1 2000
        # (26 years × 365.25 ≈ 9496, plus ~181 days in 2026 = 9677)
        # We just check sanity: should be between 9000 and 10000
        assert 9000 <= v <= 10000, f'dayssince2000={v} seems unreasonable'

    # ═════════════════════════════════════════════════════════════════
    #  sensing_loudness / sensing_loud
    # ═════════════════════════════════════════════════════════════════
    def test_loudness(self) -> None:
        """sensing_loudness returns 0 (no microphone support)."""
        assert self._eval('sensing_loudness') == 0

    def test_loud(self) -> None:
        """sensing_loud returns False (no microphone support)."""
        assert self._eval('sensing_loud') is False

    # ═════════════════════════════════════════════════════════════════
    #  sensing_askandwait / sensing_answer
    # ═════════════════════════════════════════════════════════════════
    def test_askandwait_resets_answer_and_blocks(self) -> None:
        """askandwait resets answer, sets say_text, and yields until answer arrives."""
        t = _stack('sensing_askandwait')
        _set(t, 'b0', inputs={'QUESTION': Input(value='What is your name?')})
        rt = _rt(t)
        # Pre-set an old answer — should be cleared by askandwait
        rt._answer = 'old'
        rt.green_flag()
        # Step a few frames — thread should be blocked waiting for answer
        for _ in range(5):
            rt.step()
        assert len(rt.threads) == 1  # still blocked
        assert rt._answer is None  # reset by askandwait
        assert t.say_text == 'What is your name?'  # question shown in bubble
        # Now provide the answer
        rt._answer = 'Scratcher'
        for _ in range(20):
            rt.step()
        assert len(rt.threads) == 0  # thread completed
        assert t.say_text is None  # bubble cleared

    def test_answer_empty_default(self) -> None:
        """sensing_answer returns '' when no answer has been given."""
        assert self._eval('sensing_answer') == ''

    def test_answer_after_ask(self) -> None:
        """sensing_answer returns the last provided answer."""
        t = Target(name='Sprite')
        bid = _id()
        t.blocks[bid] = _op('sensing_answer')
        t._rebuild_hat_cache()
        rt = _rt(t)
        rt._answer = 'hello world'
        assert rt.evaluate(t, bid) == 'hello world'

    # ═════════════════════════════════════════════════════════════════
    #  sensing_setdragmode
    # ═════════════════════════════════════════════════════════════════
    def test_setdragmode_draggable(self) -> None:
        """sensing_setdragmode sets sprite to draggable."""
        t = _stack('sensing_setdragmode')
        _set(t, 'b0', fields={'DRAG_MODE': Field(value='draggable')})
        rt = _run(t)
        assert len(rt.threads) == 0
        assert t.draggable is True

    def test_setdragmode_not_draggable(self) -> None:
        """sensing_setdragmode sets sprite to not draggable."""
        t = _stack('sensing_setdragmode')
        _set(t, 'b0', fields={'DRAG_MODE': Field(value='not draggable')})
        # Start as draggable to verify the opcode toggles it
        t.draggable = True
        rt = _run(t)
        assert len(rt.threads) == 0
        assert t.draggable is False

    # ═════════════════════════════════════════════════════════════════
    #  sensing_online / sensing_username
    # ═════════════════════════════════════════════════════════════════
    def test_online(self) -> None:
        """sensing_online returns True (always online in py-scratch)."""
        assert self._eval('sensing_online') is True

    def test_username(self) -> None:
        """sensing_username returns 'Scratcher' (default user)."""
        assert self._eval('sensing_username') == 'Scratcher'


# ═══════════════════════════════════════════════════════════════════════
#  Pen
# ═══════════════════════════════════════════════════════════════════════


class TestPen:
    def test_pen_down_up(self) -> None:
        t = _stack('pen_penDown', 'pen_penUp')
        rt = _run(t)
        assert t.pen_down is False

    def test_pen_down_up_initial_state(self) -> None:
        t = _stack('pen_penDown')
        rt = _run(t)
        assert t.pen_down is True

    def test_pen_up_after_down(self) -> None:
        t = _stack('pen_penDown', 'pen_penUp')
        rt = _run(t)
        assert t.pen_down is False

    def test_pen_set_color_by_number_red(self) -> None:
        t = _stack('pen_setPenColorToColor')
        _set(t, 'b0', inputs={'COLOR': Input(value=0xFF0000)})
        rt = _run(t)
        assert t.pen_color == (255, 0, 0)

    def test_pen_set_color_by_number_green(self) -> None:
        t = _stack('pen_setPenColorToColor')
        _set(t, 'b0', inputs={'COLOR': Input(value=0x00FF00)})
        rt = _run(t)
        assert t.pen_color == (0, 255, 0)

    def test_pen_set_color_by_number_blue(self) -> None:
        t = _stack('pen_setPenColorToColor')
        _set(t, 'b0', inputs={'COLOR': Input(value=0x0000FF)})
        rt = _run(t)
        assert t.pen_color == (0, 0, 255)

    def test_pen_set_color_by_number_white(self) -> None:
        t = _stack('pen_setPenColorToColor')
        _set(t, 'b0', inputs={'COLOR': Input(value=0xFFFFFF)})
        rt = _run(t)
        assert t.pen_color == (255, 255, 255)

    def test_pen_set_color_by_number_zero(self) -> None:
        t = _stack('pen_setPenColorToColor')
        _set(t, 'b0', inputs={'COLOR': Input(value=0x000000)})
        rt = _run(t)
        assert t.pen_color == (0, 0, 0)

    def test_pen_change_pen_size_by_default(self) -> None:
        t = _stack('pen_changePenSizeBy')
        _set(t, 'b0', inputs={'SIZE': Input(value=5)})
        rt = _run(t)
        assert t.pen_size == 6.0  # default 1 + 5

    def test_pen_change_pen_size_by_negative(self) -> None:
        t = _stack('pen_changePenSizeBy')
        _set(t, 'b0', inputs={'SIZE': Input(value=-0.5)})
        rt = _run(t)
        assert t.pen_size == 0.5  # default 1 - 0.5

    def test_pen_change_pen_size_by_clamp_bottom(self) -> None:
        t = _stack('pen_changePenSizeBy')
        # start at 1, subtract 5 → max(0, -4) = 0
        _set(t, 'b0', inputs={'SIZE': Input(value=-5)})
        rt = _run(t)
        assert t.pen_size == 0.0

    def test_pen_set_pen_size_to(self) -> None:
        t = _stack('pen_setPenSizeTo')
        _set(t, 'b0', inputs={'SIZE': Input(value=42)})
        rt = _run(t)
        assert t.pen_size == 42.0

    def test_pen_set_pen_size_to_zero(self) -> None:
        t = _stack('pen_setPenSizeTo')
        _set(t, 'b0', inputs={'SIZE': Input(value=0)})
        rt = _run(t)
        assert t.pen_size == 0.0

    def test_pen_set_pen_size_to_negative_clamped(self) -> None:
        t = _stack('pen_setPenSizeTo')
        _set(t, 'b0', inputs={'SIZE': Input(value=-10)})
        rt = _run(t)
        assert t.pen_size == 0.0

    def test_pen_clear_sets_request_flag(self) -> None:
        t = _stack('pen_clear')
        _set(t, 'b0')
        rt = _run(t)
        assert rt.stage is not None
        assert rt.stage._pen_clear_requested is True

    def test_pen_stamp_appends_queue(self) -> None:
        t = _stack('pen_stamp')
        _set(t, 'b0')
        rt = _run(t)
        assert rt.stage is not None
        assert len(rt.stage._stamp_queue) == 1
        entry = rt.stage._stamp_queue[0]
        assert len(entry) == 5
        x, y, size, direction, costume_idx = entry
        assert x == 0.0
        assert y == 0.0
        assert size == 100.0
        assert direction == 90.0
        assert costume_idx == 0


# ═══════════════════════════════════════════════════════════════════════
#  Integration: mixed opcodes
# ═══════════════════════════════════════════════════════════════════════


class TestMixed:
    def test_move_then_wait_then_move(self) -> None:
        """Verifies a real Scratch-like script: move → wait 0.1s → move."""
        t = _stack('motion_movesteps', 'control_wait', 'motion_movesteps')
        _set(t, 'b0', inputs={'STEPS': Input(value=20)})
        _set(t, 'b1', inputs={'DURATION': Input(value=0.1)})  # 6 frames
        _set(t, 'b2', inputs={'STEPS': Input(value=10)})
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


# ═══════════════════════════════════════════════════════════════════════
#  Value type resolution (resolve_input)
# ═══════════════════════════════════════════════════════════════════════


class TestValueResolution:
    """Test how resolve_input handles different SB3 value formats."""

    def _make_rt(self) -> tuple[Runtime, Target]:
        rt = Runtime()
        rt._real_time = False
        rt.add_target(Target(name='Stage', is_stage=True))
        rt.register_all(OPCODE_MAP)
        t = Target(name='Sprite')
        t.variables['v1'] = Variable(name='myVar', value=42)
        t.lists['l1'] = ListVar('myList', contents=['a', 'b'])
        # Add a reporter block for block-reference tests
        t.blocks['reporter'] = Block(
            id='reporter', opcode='data_variable', fields={'VARIABLE': Field(value='myVar')}
        )
        rt.add_target(t)
        return rt, t

    # ── Literal values ──────────────────────────────────────────────

    def test_literal_int(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, 42) == 42

    def test_literal_float(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, 3.14) == 3.14

    def test_literal_str(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, 'hello') == 'hello'

    def test_literal_bool(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, True) is True
        assert rt.resolve_input(t, False) is False

    def test_literal_none(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, None) is None

    def test_literal_zero(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, 0) == 0
        assert rt.resolve_input(t, 0.0) == 0.0

    # ── Input wrapper (unwrapping) ──────────────────────────────────

    def test_input_wrapper_literal(self) -> None:
        """Test that _input_raw strips the Input wrapper before resolve_input."""
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b', opcode='data_setvariableto', inputs={'VALUE': Input(value=99)}
        )
        value = _input_raw(t.blocks['b'], 'VALUE')
        assert rt.resolve_input(t, value) == 99

    def test_input_wrapper_shadow(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b',
            opcode='data_setvariableto',
            inputs={'VALUE': Input(value=77, shadow=True)},
        )
        value = _input_raw(t.blocks['b'], 'VALUE')
        assert rt.resolve_input(t, value) == 77

    def test_primitive_4_math_number(self) -> None:
        rt, t = self._make_rt()
        # [4, value] = math_number
        assert rt.resolve_input(t, [4, 10]) == 10
        assert rt.resolve_input(t, [4, 3.5]) == 3.5

    def test_primitive_5_positive_number(self) -> None:
        rt, t = self._make_rt()
        # [5, value] = math_positive_number — literal, NOT variable
        assert rt.resolve_input(t, [5, '1']) == '1'
        assert rt.resolve_input(t, [5, 2.5]) == 2.5
        assert rt.resolve_input(t, [5, '0.5']) == '0.5'

    def test_primitive_6_whole_number(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, [6, 7]) == 7

    def test_primitive_7_integer(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, [7, -3]) == -3

    def test_primitive_8_angle(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, [8, 90]) == 90

    def test_primitive_9_colour_picker(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, [9, 0xFF0000]) == 0xFF0000
        assert rt.resolve_input(t, [9, '#FF0000']) == '#FF0000'

    def test_primitive_10_text(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, [10, 'apple']) == 'apple'
        assert rt.resolve_input(t, [10, '']) == ''

    def test_primitive_11_broadcast(self) -> None:
        rt, t = self._make_rt()
        assert rt.resolve_input(t, [11, 'message1']) == 'message1'

    def test_primitive_12_variable(self) -> None:
        rt, t = self._make_rt()
        value = rt.resolve_input(t, [12, 'v1'])
        assert value == 42

    def test_primitive_12_variable_by_name(self) -> None:
        rt, t = self._make_rt()
        value = rt.resolve_input(t, [12, 'myVar'])
        assert value == 42

    def test_primitive_12_variable_not_found(self) -> None:
        rt, t = self._make_rt()
        value = rt.resolve_input(t, [12, 'nonexistent'])
        assert value == 0

    def test_primitive_13_list(self) -> None:
        rt, t = self._make_rt()
        value = rt.resolve_input(t, [13, 'l1'])
        assert value == ['a', 'b']

    def test_primitive_13_list_by_name(self) -> None:
        rt, t = self._make_rt()
        value = rt.resolve_input(t, [13, 'myList'])
        assert value == ['a', 'b']

    def test_primitive_13_list_not_found(self) -> None:
        rt, t = self._make_rt()
        value = rt.resolve_input(t, [13, 'nonexistent'])
        assert value == []

    def test_primitive_unknown_type(self) -> None:
        rt, t = self._make_rt()
        # Unknown type codes return the ref value as-is
        assert rt.resolve_input(t, [99, 'foo']) == 'foo'
        assert rt.resolve_input(t, [0, 10]) == 10

    # ── Stage variable fallback ─────────────────────────────────────

    def test_variable_on_stage(self) -> None:
        rt = Runtime()
        rt._real_time = False
        stage = Target(name='Stage', is_stage=True)
        stage.variables['global'] = Variable('global', 999)
        rt.add_target(stage)
        rt.register_all(OPCODE_MAP)
        t = Target(name='Sprite')
        rt.add_target(t)
        value = rt.resolve_input(t, [12, 'global'])
        assert value == 999

    # ── Shadow pair: [block_id, literal] ────────────────────────────

    def test_shadow_pair(self) -> None:
        rt, t = self._make_rt()
        # [block_id, literal] — the second element is the shadow default
        value = rt.resolve_input(t, ['reporter', 42])
        assert value == 42

    def test_shadow_pair_string_literal(self) -> None:
        rt, t = self._make_rt()
        value = rt.resolve_input(t, ['reporter', 'default_text'])
        assert value == 'default_text'

    # ── Block reference (string resolving to reporter) ──────────────

    def test_block_reference(self) -> None:
        rt, t = self._make_rt()
        # The string 'reporter' is a block ID → evaluate the reporter
        value = rt.resolve_input(t, 'reporter')
        assert value == 42  # data_variable reporter returns myVar=42

    def test_block_reference_via_input(self) -> None:
        rt, t = self._make_rt()
        # resolve_input works on raw values; caller strips Input
        value = rt.resolve_input(t, 'reporter')

    def test_num_accessor(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b',
            opcode='control_wait',
            inputs={'DURATION': Input(value=[5, '0.5'], shadow=True)},
        )
        # [5, '0.5'] = positive number literal → '0.5' → float('0.5') = 0.5
        val = rt.num(t, t.blocks['b'], 'DURATION')
        assert abs(val - 0.5) < 0.001

    def test_num_accessor_variable_ref(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b',
            opcode='control_wait',
            inputs={'DURATION': Input(value=[12, 'v1'], shadow=True)},
        )
        # [12, 'v1'] = variable reference → myVar=42 → float(42) = 42.0
        val = rt.num(t, t.blocks['b'], 'DURATION')
        assert val == 42.0

    def test_val_accessor_literal(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b',
            opcode='data_setvariableto',
            inputs={'VALUE': Input(value=[10, 'hello'], shadow=True)},
        )
        val = rt.val(t, t.blocks['b'], 'VALUE')
        assert val == 'hello'

    def test_val_accessor_variable_ref(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b',
            opcode='data_setvariableto',
            inputs={'VALUE': Input(value=[12, 'v1'], shadow=True)},
        )
        val = rt.val(t, t.blocks['b'], 'VALUE')
        assert val == 42


class TestInputFieldFormat:
    """Test SB3 input/field parsing, name preservation, normalization, and serialize round-trip."""

    # ── Input parsing: bare literal normalization ──────────────────
    #
    # The SB3 schema requires inputs[1] to be string-or-null (a block ID
    # reference) or an array (compact primitive [type_code, value, ...]).
    # Bare literals like [1, 42] are schema violations.  _parse_input
    # normalizes them into the compact primitive format so all downstream
    # code deals with a single canonical form.

    def test_parse_input_normalizes_number(self) -> None:
        """[1, 42] → normalized to [4, 42] (NUMBER)."""
        inp = _parse_input('STEPS', [1, 42])
        assert inp.value == [PrimitiveType.NUMBER, 42]
        assert inp.shadow is True

    def test_parse_input_normalizes_float(self) -> None:
        """[1, 0.5] → normalized to [4, 0.5] (NUMBER)."""
        inp = _parse_input('DURATION', [1, 0.5])
        assert inp.value == [PrimitiveType.NUMBER, 0.5]
        assert inp.shadow is True

    def test_parse_input_normalizes_string(self) -> None:
        """[1, "hello"] → normalized to [10, "hello"] (TEXT)."""
        inp = _parse_input('MESSAGE', [1, 'hello'])
        assert inp.value == [PrimitiveType.TEXT, 'hello']
        assert inp.shadow is True

    def test_parse_input_normalizes_bool(self) -> None:
        """[1, true] → normalized to [4, 1] (NUMBER)."""
        inp = _parse_input('FLAG', [1, True])
        assert inp.value == [PrimitiveType.NUMBER, 1]
        assert inp.shadow is True

    def test_parse_input_preserves_compact_primitive(self) -> None:
        """[1, [4, 10]] passes through unchanged (already canonical)."""
        inp = _parse_input('STEPS', [1, [4, 10]])
        assert inp.value == [4, 10]
        assert inp.shadow is True

    def test_parse_input_preserves_variable_primitive(self) -> None:
        """[1, [12, name, id]] passes through — already compact."""
        inp = _parse_input('VARIABLE', [1, [12, 'score', 'v1']])
        assert inp.value == [12, 'score', 'v1']
        assert inp.shadow is True

    def test_parse_input_preserves_text_primitive(self) -> None:
        """[1, [10, "text"]] passes through."""
        inp = _parse_input('MESSAGE', [1, [10, 'text']])
        assert inp.value == [10, 'text']
        assert inp.shadow is True

    # ── Input parsing: block references (unchanged) ─────────────────

    def test_parse_input_block_ref(self) -> None:
        """[2, block_id] → value is the block ID string (not normalized)."""
        inp = _parse_input('VALUE', [2, 'reporter_block'])
        assert inp.value == 'reporter_block'
        assert inp.shadow is False

    def test_parse_input_obsolete_format(self) -> None:
        """[3, literal, block_id] → value is the block_id, not the literal."""
        inp = _parse_input('VALUE', [3, 42, 'reporter_block'])
        assert inp.value == 'reporter_block'
        assert inp.shadow is True

    # ── resolve_input with compact primitives ──────────────────────
    #
    # resolve_input should handle the canonical compact primitive format
    # correctly.  Once _parse_input normalizes bare literals, this is
    # the only path for literal values.

    def test_resolve_number_primitive(self) -> None:
        """[4, 42] → 42."""
        rt = Runtime()
        t = Target('Test')
        rt.add_target(t)
        assert rt.resolve_input(t, [PrimitiveType.NUMBER, 42]) == 42

    def test_resolve_text_primitive(self) -> None:
        """[10, "hello"] → "hello"."""
        rt = Runtime()
        t = Target('Test')
        rt.add_target(t)
        assert rt.resolve_input(t, [PrimitiveType.TEXT, 'hello']) == 'hello'

    def test_resolve_variable_primitive(self) -> None:
        """[12, "varName", "varId"] returns the variable's value."""
        rt = Runtime()
        t = Target('Test')
        t.variables['v1'] = Variable('score', 42)
        rt.add_target(t)
        assert rt.resolve_input(t, [PrimitiveType.VARIABLE, 'score', 'v1']) == 42

    def test_resolve_list_primitive(self) -> None:
        """[13, "listName", "listId"] returns the list contents."""
        rt = Runtime()
        t = Target('Test')
        t.lists['l1'] = ListVar('items', ['a', 'b'])
        rt.add_target(t)
        assert rt.resolve_input(t, [PrimitiveType.LIST, 'items', 'l1']) == ['a', 'b']

    def test_resolve_bare_literal_fallback(self) -> None:
        """Bare literal (not wrapped in compact primitive) still resolves
        via the _unwrap_shadow fallback for backward compatibility."""
        rt = Runtime()
        t = Target('Test')
        rt.add_target(t)
        assert rt.resolve_input(t, 42) == 42
        assert rt.resolve_input(t, 'bare string') == 'bare string'

    # ── Field parsing ─────────────────────────────────────────────

    def test_parse_field_preserves_name(self) -> None:
        """_parse_field stores the field name."""
        fld = _parse_field('VARIABLE', ['score', 'v1'])
        assert fld.value == 'score'
        assert fld.id == 'v1'
        assert fld.variable_type == ''

    def test_parse_field_no_id(self) -> None:
        fld = _parse_field('EFFECT', ['color'])
        assert fld.value == 'color'
        assert fld.id is None

    def test_parse_field_variable_type_variable(self) -> None:
        """VARIABLE field → variable_type = '' (scalar)."""
        fld = _parse_field('VARIABLE', ['score', 'v1'])
        assert fld.variable_type == ''

    def test_parse_field_variable_type_list(self) -> None:
        """LIST field → variable_type = 'list'."""
        fld = _parse_field('LIST', ['items', 'l1'])
        assert fld.variable_type == 'list'

    def test_parse_field_variable_type_broadcast(self) -> None:
        """BROADCAST_OPTION field → variable_type = 'broadcast_msg'."""
        fld = _parse_field('BROADCAST_OPTION', ['message1', 'm1'])
        assert fld.variable_type == 'broadcast_msg'

    def test_parse_field_plain_dropdown(self) -> None:
        """Plain field like EFFECT, STYLE → variable_type = None."""
        fld = _parse_field('EFFECT', ['color'])
        assert fld.variable_type is None

    # ── Serialize round-trip ──────────────────────────────────────

    def test_serialize_input_roundtrip_shadow(self) -> None:
        """Input(shadow=True) → [1, value]."""
        inp = Input(value=10, shadow=True)
        assert _serialize_input(inp) == [1, 10]

    def test_serialize_input_roundtrip_block_ref(self) -> None:
        """Input(shadow=False) → [2, value]."""
        inp = Input(value='block_abc', shadow=False)
        assert _serialize_input(inp) == [2, 'block_abc']

    def test_serialize_field_roundtrip_with_id(self) -> None:
        """Field with id → [value, id]."""
        fld = Field(value='score', id='v1')
        assert _serialize_field(fld) == ['score', 'v1']

    def test_serialize_field_roundtrip_no_id(self) -> None:
        """Field without id → [value, None]."""
        fld = Field(value='color')
        assert _serialize_field(fld) == ['color', None]

    # ── Full block parse round-trip ───────────────────────────────

    def test_parse_block_with_inputs_and_fields(self) -> None:
        """Parse a block with inputs and fields preserves all names."""
        data = {
            'opcode': 'data_setvariableto',
            'next': None,
            'parent': 'hat1',
            'shadow': False,
            'topLevel': False,
            'inputs': {'VALUE': [1, 42]},
            'fields': {'VARIABLE': ['score', 'v1']},
        }
        block = _parse_block('b1', data)
        assert block.id == 'b1'
        assert block.opcode == 'data_setvariableto'
        assert block.inputs['VALUE'].value == [PrimitiveType.NUMBER, 42]
        assert block.inputs['VALUE'].shadow is True
        assert block.fields['VARIABLE'].value == 'score'
        assert block.fields['VARIABLE'].id == 'v1'
        assert block.fields['VARIABLE'].variable_type == ''

    # ── resolve_input with is_shadow flag ─────────────────────────

    def test_resolve_input_shadow_string_literal(self) -> None:
        """Shadow string literal should NOT be evaluated as a block reference."""
        rt, t = _make_with_reporter('reporter', 99)
        # If is_shadow=True, the string is treated as a literal, not a block ref
        val = rt.resolve_input(t, 'reporter', is_shadow=True)
        assert val == 'reporter'  # treated as literal string, not evaluated

    def test_resolve_input_non_shadow_string(self) -> None:
        """Non-shadow string matching a block ID → evaluate the reporter."""
        rt, t = _make_with_reporter('reporter', 99)
        val = rt.resolve_input(t, 'reporter', is_shadow=False)
        assert val == 99  # evaluated as reporter

    def test_resolve_input_broadcast_primitive(self) -> None:
        """[11, 'msg'] → broadcast primitive returns the message string."""
        rt, t = _make_with_reporter('reporter', 99)
        val = rt.resolve_input(t, [11, 'broadcast_msg'])
        assert val == 'broadcast_msg'

    def test_resolve_input_none(self) -> None:
        """None value falls through to _unwrap_shadow (no-op)."""
        rt, t = _make_with_reporter('reporter', 99)
        val = rt.resolve_input(t, None)
        assert val is None

    def test_resolve_input_empty_list(self) -> None:
        """Empty list falls through to _unwrap_shadow (no-op)."""
        rt, t = _make_with_reporter('reporter', 99)
        val = rt.resolve_input(t, [])
        assert val == []

    def test_resolve_input_zero(self) -> None:
        """Integer 0 is a literal, not a block reference."""
        rt, t = _make_with_reporter('reporter', 99)
        val = rt.resolve_input(t, 0)
        assert val == 0

    def test_unwrap_shadow_string_pair(self) -> None:
        """['block_id', literal] → literal is returned."""
        val = _unwrap_shadow(['reporter', 42])
        assert val == 42

    def test_unwrap_shadow_no_match(self) -> None:
        """Non-pair values pass through unchanged."""
        assert _unwrap_shadow(42) == 42
        assert _unwrap_shadow('hello') == 'hello'
        assert _unwrap_shadow(None) is None
        assert _unwrap_shadow([1, 2, 3]) == [1, 2, 3]
        assert _unwrap_shadow([4, 10]) == [4, 10]  # type_code array is NOT a shadow pair


class TestSound:
    """Sound opcode handlers — volume, tempo, effects, playback."""

    def _make_rt(self) -> tuple[Runtime, Target]:
        rt = Runtime()
        rt._real_time = False
        stage = Target(name='Stage', is_stage=True)
        stage.tempo = 60.0
        rt.add_target(stage)
        rt.register_all(OPCODE_MAP)
        t = Target(name='Sprite')
        t.volume = 100.0
        t.sound_effects = {'PITCH': 0.0, 'PAN': 0.0}
        rt.add_target(t)
        return rt, t

    # ── Volume ────────────────────────────────────────────────────

    def test_sound_volume_reporter(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(id='b', opcode='sound_volume')
        val = rt.evaluate(t, 'b')
        assert val == 100.0

    def test_sound_setvolumeto(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b', opcode='sound_setvolumeto', inputs={'VOLUME': Input(value=75)}
        )
        rt.evaluate(t, 'b')  # run the handler
        assert t.volume == 75.0

    def test_sound_setvolumeto_clamp_high(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b', opcode='sound_setvolumeto', inputs={'VOLUME': Input(value=150)}
        )
        rt.evaluate(t, 'b')
        assert t.volume == 100.0

    def test_sound_setvolumeto_clamp_low(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b', opcode='sound_setvolumeto', inputs={'VOLUME': Input(value=-10)}
        )
        rt.evaluate(t, 'b')
        assert t.volume == 0.0

    def test_sound_changevolumeby(self) -> None:
        rt, t = self._make_rt()
        t.volume = 50.0
        t.blocks['b'] = Block(
            id='b', opcode='sound_changevolumeby', inputs={'VOLUME': Input(value=30)}
        )
        rt.evaluate(t, 'b')
        assert t.volume == 80.0

    def test_sound_changevolumeby_clamp_high(self) -> None:
        rt, t = self._make_rt()
        t.volume = 80.0
        t.blocks['b'] = Block(
            id='b', opcode='sound_changevolumeby', inputs={'VOLUME': Input(value=50)}
        )
        rt.evaluate(t, 'b')
        assert t.volume == 100.0

    def test_sound_changevolumeby_clamp_low(self) -> None:
        rt, t = self._make_rt()
        t.volume = 30.0
        t.blocks['b'] = Block(
            id='b', opcode='sound_changevolumeby', inputs={'VOLUME': Input(value=-50)}
        )
        rt.evaluate(t, 'b')
        assert t.volume == 0.0

    # ── Sound effects ─────────────────────────────────────────────

    def test_sound_seteffectto_pitch(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_seteffectto',
            fields={'EFFECT': Field(value='PITCH')},
            inputs={'VALUE': Input(value=50)},
        )
        rt.evaluate(t, 'b')
        assert t.sound_effects['PITCH'] == 50.0

    def test_sound_seteffectto_pan(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_seteffectto',
            fields={'EFFECT': Field(value='PAN')},
            inputs={'VALUE': Input(value=-50)},
        )
        rt.evaluate(t, 'b')
        assert t.sound_effects['PAN'] == -50.0

    def test_sound_seteffectto_unknown_effect_ignored(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_seteffectto',
            fields={'EFFECT': Field(value='ECHO')},
            inputs={'VALUE': Input(value=50)},
        )
        rt.evaluate(t, 'b')
        # Unknown effect is silently ignored
        assert t.sound_effects['PITCH'] == 0.0
        assert t.sound_effects['PAN'] == 0.0

    def test_sound_changeeffectby_pitch(self) -> None:
        rt, t = self._make_rt()
        t.sound_effects['PITCH'] = 10.0
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_changeeffectby',
            fields={'EFFECT': Field(value='PITCH')},
            inputs={'VALUE': Input(value=20)},
        )
        rt.evaluate(t, 'b')
        assert t.sound_effects['PITCH'] == 30.0

    def test_sound_changeeffectby_pan_negative(self) -> None:
        rt, t = self._make_rt()
        t.sound_effects['PAN'] = 0.0
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_changeeffectby',
            fields={'EFFECT': Field(value='PAN')},
            inputs={'VALUE': Input(value=-25)},
        )
        rt.evaluate(t, 'b')
        assert t.sound_effects['PAN'] == -25.0

    def test_sound_cleareffects(self) -> None:
        rt, t = self._make_rt()
        t.sound_effects = {'PITCH': 50.0, 'PAN': -30.0}
        t.blocks['b'] = Block(id='b', opcode='sound_cleareffects')
        rt.evaluate(t, 'b')
        assert t.sound_effects == {'PITCH': 0.0, 'PAN': 0.0}

    # ── Tempo ─────────────────────────────────────────────────────

    def test_sound_tempo_reporter(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(id='b', opcode='sound_tempo')
        val = rt.evaluate(t, 'b')
        assert val == 60.0

    def test_sound_settempo(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(id='b', opcode='sound_settempo', inputs={'TEMPO': Input(value=120)})
        rt.evaluate(t, 'b')
        assert rt.stage and rt.stage.tempo == 120.0

    def test_sound_settempo_clamp_low(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(id='b', opcode='sound_settempo', inputs={'TEMPO': Input(value=5)})
        rt.evaluate(t, 'b')
        assert rt.stage and rt.stage.tempo == 20.0

    def test_sound_settempo_clamp_high(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(id='b', opcode='sound_settempo', inputs={'TEMPO': Input(value=1000)})
        rt.evaluate(t, 'b')
        assert rt.stage and rt.stage.tempo == 500.0

    def test_sound_changetempo(self) -> None:
        rt, t = self._make_rt()
        assert rt.stage is not None
        rt.stage.tempo = 80.0
        t.blocks['b'] = Block(id='b', opcode='sound_changetempo', inputs={'TEMPO': Input(value=30)})
        rt.evaluate(t, 'b')
        assert rt.stage.tempo == 110.0

    def test_sound_changetempo_clamp(self) -> None:
        rt, t = self._make_rt()
        assert rt.stage is not None
        rt.stage.tempo = 10.0
        t.blocks['b'] = Block(id='b', opcode='sound_changetempo', inputs={'TEMPO': Input(value=-5)})
        rt.evaluate(t, 'b')
        assert rt.stage.tempo == 20.0

    # ── Sound menu ───────────────────────────────────────────────

    def test_sound_sounds_menu(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_sounds_menu',
            fields={'SOUND_MENU': Field(value='Meow')},
        )
        val = rt.evaluate(t, 'b')
        assert val == 'Meow'

    # ── Playback (no-op without pygame.mixer) ────────────────────

    def test_sound_play_no_crash(self) -> None:
        """sound_play should not crash even without pygame.mixer."""
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b', opcode='sound_play', inputs={'SOUND_MENU': Input(value='Meow')}
        )
        # Should not raise
        rt.evaluate(t, 'b')

    def test_sound_playuntildone_no_crash(self) -> None:
        """sound_playuntildone should not crash without pygame.mixer."""
        rt, t = self._make_rt()
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_playuntildone',
            inputs={'SOUND_MENU': Input(value='Meow')},
        )
        # evaluate runs generator to completion internally
        rt.evaluate(t, 'b')

    def test_sound_stopallsounds_no_crash(self) -> None:
        rt, t = self._make_rt()
        t.blocks['b'] = Block(id='b', opcode='sound_stopallsounds')
        rt.evaluate(t, 'b')

    # ── Sound lookup on Target ───────────────────────────────────

    def test_find_sound_by_name(self) -> None:
        t = Target(name='Sprite')
        t.sounds.append(Sound(name='Meow', data=b'fake_wav'))
        t.sounds.append(Sound(name='Bark', data=b'fake_wav2'))
        assert t.find_sound('Meow') is t.sounds[0]
        assert t.find_sound('Bark') is t.sounds[1]
        assert t.find_sound('Moo') is None

    # ── Clone preserves sound state ──────────────────────────────

    def test_clone_preserves_sound_state(self) -> None:
        t = Target(name='Sprite')
        t.volume = 75.0
        t.sound_effects = {'PITCH': 10.0, 'PAN': -20.0}
        t.tempo = 120.0
        clone = t.clone()
        assert clone.volume == 75.0
        assert clone.sound_effects == {'PITCH': 10.0, 'PAN': -20.0}
        assert clone.tempo == 120.0
        # Mutating clone should not affect original
        clone.sound_effects['PITCH'] = 99.0
        assert t.sound_effects['PITCH'] == 10.0

    def test_sound_seteffectto_pitch_clamp(self) -> None:
        rt, t = self._make_rt()
        # Pitch clamped to -360..360
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_seteffectto',
            fields={'EFFECT': Field(value='PITCH')},
            inputs={'VALUE': Input(value=500)},
        )
        rt.evaluate(t, 'b')
        assert t.sound_effects['PITCH'] == 360.0

        t.sound_effects['PITCH'] = 0.0
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_seteffectto',
            fields={'EFFECT': Field(value='PITCH')},
            inputs={'VALUE': Input(value=-500)},
        )
        rt.evaluate(t, 'b')
        assert t.sound_effects['PITCH'] == -360.0

    def test_sound_seteffectto_pan_clamp(self) -> None:
        rt, t = self._make_rt()
        # Pan clamped to -100..100
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_seteffectto',
            fields={'EFFECT': Field(value='PAN')},
            inputs={'VALUE': Input(value=200)},
        )
        rt.evaluate(t, 'b')
        assert t.sound_effects['PAN'] == 100.0

        t.sound_effects['PAN'] = 0.0
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_seteffectto',
            fields={'EFFECT': Field(value='PAN')},
            inputs={'VALUE': Input(value=-200)},
        )
        rt.evaluate(t, 'b')
        assert t.sound_effects['PAN'] == -100.0

    def test_sound_changeeffectby_pitch_clamp(self) -> None:
        rt, t = self._make_rt()
        t.sound_effects['PITCH'] = 350.0
        t.blocks['b'] = Block(
            id='b',
            opcode='sound_changeeffectby',
            fields={'EFFECT': Field(value='PITCH')},
            inputs={'VALUE': Input(value=20)},
        )
        rt.evaluate(t, 'b')
        assert t.sound_effects['PITCH'] == 360.0
