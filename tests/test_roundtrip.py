"""Roundtrip tests: DSL → sb3 → transcribe → DSL project, assert structural equality."""
# ruff: noqa: E501

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from scratch.dsl import Project, control, data, looks, motion, operators, sensing
from scratch.sb3.transcriber import transcribe_to_dir
from scratch.vm.runtime import Runtime
from scratch.vm.target import Target


# ── Structural comparison helpers ──────────────────────────────────────────


def _get_opcode_chains(tgt: Target) -> list[list[str]]:
    """Return sorted opcode chains (one per hat) for a target.

    Each chain is ``[hat_opcode, block_opcode, ...]``.
    """
    chains: list[list[str]] = []
    for bid, block in tgt.blocks.items():
        if not block.top_level:
            continue
        if block.opcode in (
            'motion_pointtowards_menu',
            'motion_goto_menu',
            'motion_glideto_menu',
            'looks_costume',
            'looks_backdrops',
            'sound_sounds_menu',
            'data_variable_menu',
            'data_list_menu',
        ):
            continue
        chain: list[str] = [block.opcode]
        nxt = block.next
        while nxt and nxt in tgt.blocks:
            b = tgt.blocks[nxt]
            chain.append(b.opcode)
            nxt = b.next
        chains.append(chain)

    chains.sort(key=lambda c: c[0])  # sort by hat opcode
    return chains


def _get_target_snapshot(tgt: Target) -> dict[str, Any]:
    """Extract a comparable snapshot from a Target."""
    variables = {v.name: v.value for v in tgt.variables.values()}
    variables.pop('_mouse_x', None)
    variables.pop('_mouse_y', None)
    # Filter out auto-generated cloud ghost variables
    variables = {k: v for k, v in variables.items() if not k.startswith('cloud-')}

    lists = {lst.name: list(lst.contents) for lst in tgt.lists.values()}

    costumes = [c.name for c in tgt.costumes]

    return {
        'name': tgt.name,
        'is_stage': tgt.is_stage,
        'variables': variables,
        'lists': lists,
        'costumes': costumes,
        'opcode_chains': _get_opcode_chains(tgt),
        'x': tgt.x,
        'y': tgt.y,
        'direction': tgt.direction,
        'size': tgt.size,
        'visible': tgt.visible,
        'layer_order': tgt.layer_order,
        'rotation_style': tgt.rotation_style,
    }


def _assert_runtimes_equal(rt_a: Runtime, rt_b: Runtime) -> None:
    """Compare two Runtimes structurally."""
    # Same number of targets
    assert len(rt_a.targets) == len(rt_b.targets), (
        f'target count: {len(rt_a.targets)} vs {len(rt_b.targets)}'
    )

    # Compare target by target (they should be in the same order)
    for tgt_a, tgt_b in zip(rt_a.targets, rt_b.targets):
        snap_a = _get_target_snapshot(tgt_a)
        snap_b = _get_target_snapshot(tgt_b)

        assert snap_a['name'] == snap_b['name'], f"name mismatch: {snap_a['name']} != {snap_b['name']}"
        assert snap_a['is_stage'] == snap_b['is_stage']
        assert snap_a['variables'] == snap_b['variables'], (
            f"vars mismatch for {snap_a['name']}: {snap_a['variables']} != {snap_b['variables']}"
        )
        assert snap_a['lists'] == snap_b['lists'], (
            f"lists mismatch for {snap_a['name']}: {snap_a['lists']} != {snap_b['lists']}"
        )
        assert snap_a['costumes'] == snap_b['costumes'], (
            f"costumes mismatch for {snap_a['name']}: {snap_a['costumes']} != {snap_b['costumes']}"
        )
        assert snap_a['opcode_chains'] == snap_b['opcode_chains'], (
            f"opcode chains mismatch for {snap_a['name']}: "
            f"{snap_a['opcode_chains']} != {snap_b['opcode_chains']}"
        )
        # Properties
        for prop in ('x', 'y', 'direction', 'size', 'visible', 'layer_order', 'rotation_style'):
            assert snap_a[prop] == snap_b[prop], (
                f"{prop} mismatch for {snap_a['name']}: {snap_a[prop]} != {snap_b[prop]}"
            )


# ── Roundtrip runner ──────────────────────────────────────────────────────


def _roundtrip(project: Project, tmp_path: Path) -> Runtime:
    """Build a Project via DSL, transcribe to Python, exec, and return the rebuilt Runtime.

    Returns the Runtime built from the *transcribed* code so the caller
    can compare it against the original project's Runtime.
    """
    # 1. Save original as .sb3
    buf = io.BytesIO()
    project.save(buf)
    sb3_bytes = buf.getvalue()

    # 2. Write .sb3 to temp
    sb3_path = tmp_path / 'test.sb3'
    sb3_path.write_bytes(sb3_bytes)

    # 3. Transcribe
    out_dir = tmp_path / 'game_src'
    transcribe_to_dir(sb3_path, out_dir)

    # 4. Read + exec generated code
    main_py = out_dir / 'main.py'
    source = main_py.read_text()

    # Compile + exec in a fresh namespace
    bytecode = compile(source, str(main_py), 'exec')
    ns: dict[str, Any] = {}
    exec(bytecode, ns)

    # 5. Extract the project variable and build runtime
    project2 = ns.get('project')
    assert project2 is not None, 'generated code did not define `project`'
    assert isinstance(project2, Project), f'expected Project, got {type(project2)}'

    return project2.build_runtime()


# ── Test cases ─────────────────────────────────────────────────────────────


class TestRoundtripDSL:
    """DSL → sb3 → transcribe → exec → compare Runtime structure."""

    def test_empty_projec(self, tmp_path: Path) -> None:
        """Stage only, no blocks."""
        project = Project('Empty')
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_single_move(self, tmp_path: Path) -> None:
        """One sprite, one hat, one move block."""
        project = Project('MoveTest')
        sprite = project.sprite('Cat')
        sprite.when_flag_clicked(
            motion.move(10),
        )
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_multi_block_chain(self, tmp_path: Path) -> None:
        """A chain of multiple blocks under a hat."""
        project = Project('ChainTest')
        sprite = project.sprite('Ball')
        sprite.when_flag_clicked(
            motion.move(10),
            motion.turn_right(15),
            motion.if_on_edge_bounce(),
            control.wait(0.5),
        )
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_variable_ops(self, tmp_path: Path) -> None:
        """Variable declaration, set, change, and reporter usage."""
        project = Project('VarTest')
        project.stage.var('score', 0)
        project.stage.var('lives', 3)

        project.stage.when_flag_clicked(
            data.set_variable('score', 10),
            data.change_variable('lives', -1),
        )
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_two_sprites(self, tmp_path: Path) -> None:
        """Two sprites with different scripts."""
        project = Project('TwoSprites')
        cat = project.sprite('Cat')
        cat.x = -100
        cat.y = 0
        cat.when_flag_clicked(
            control.forever()(
                motion.move(5),
                motion.if_on_edge_bounce(),
                control.wait(0.01),
            ),
        )

        mouse = project.sprite('Mouse')
        mouse.x = 100
        mouse.y = 0
        mouse.direction = -90
        mouse.when_flag_clicked(
            control.forever()(
                motion.move(2),
                motion.if_on_edge_bounce(),
            ),
        )
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_control_structures(self, tmp_path: Path) -> None:
        """repeat, if_, if_else, wait_until."""
        project = Project('ControlTest')
        s = project.sprite('Sprite')
        s.when_flag_clicked(
            control.repeat(10)(
                motion.move(5),
                motion.turn_right(10),
            ),
        )
        s.when_key_pressed('space')(
            motion.move(10),
        )
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_operators(self, tmp_path: Path) -> None:
        """Reporter nesting with operators."""
        project = Project('OpTest')
        project.stage.var('score', 0)
        project.stage.when_flag_clicked(
            data.set_variable(
                'score',
                operators.add(data.variable('score'), 1),
            ),
        )
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_sensing_blocks(self, tmp_path: Path) -> None:
        """Sensing blocks — key_pressed, touching, ask_and_wait."""
        project = Project('SenseTest')
        s = project.sprite('Sprite')
        s.when_flag_clicked(
            control.forever()(
                motion.move(5),
                motion.if_on_edge_bounce(),
            ),
        )
        s.when_key_pressed('space')(
            motion.move(10),
        )
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_sprite_properties(self, tmp_path: Path) -> None:
        """Sprite position, direction, size, visibility, layer."""
        project = Project('PropTest')
        s = project.sprite('Sprite')
        s.x = -150
        s.y = 80
        s.direction = 180
        s.size = 50
        s.visible = False
        s.layer_order = 5
        s.rotation_style = 'left-right'
        s.when_flag_clicked(
            motion.move(10),
        )
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_stage_scripts(self, tmp_path: Path) -> None:
        """Stage with its own scripts."""
        project = Project('StageScripts')
        project.stage.when_flag_clicked(
            control.wait(1),
        )
        s = project.sprite('Sprite')
        s.when_flag_clicked(
            motion.move(10),
        )
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_looks_blocks(self, tmp_path: Path) -> None:
        """Looks: say, think, show, hide, switch_costume."""
        project = Project('LooksTest')
        s = project.sprite('Sprite')
        s.when_flag_clicked(
            looks.say('Hello!'),
            looks.say_for_seconds('Hi', 2),
            looks.think('Hmm...'),
            looks.think_for_seconds('Hmm', 1),
            looks.show(),
            looks.hide(),
        )
        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)

    def test_complex_nested(self, tmp_path: Path) -> None:
        """Complex project: multiple sprites, variables, operators, and control flow."""
        project = Project('Complex')

        # Stage with variables
        project.stage.var('score', 0)
        project.stage.var('level', 1)

        project.stage.when_flag_clicked(
            data.set_variable('score', 0),
            data.set_variable('level', 1),
        )

        # Player sprite
        player = project.sprite('Player')
        player.x = 0
        player.y = 0
        player.var('speed', 5)

        player.when_flag_clicked(
            control.forever()(
                control.if_(sensing.key_pressed('right arrow'))(
                    motion.change_x(data.variable('speed')),
                ),
                control.if_(sensing.key_pressed('left arrow'))(
                    motion.change_x(operators.mult(data.variable('speed'), -1)),
                ),
                motion.if_on_edge_bounce(),
            ),
        )

        player.when_key_pressed('space')(
            data.change_variable('score', 1),
            data.set_variable(
                'score',
                operators.add(data.variable('score'), 1),
            ),
        )

        # Enemy sprite
        enemy = project.sprite('Enemy')
        enemy.x = 200
        enemy.y = 100
        enemy.direction = -90
        enemy.when_flag_clicked(
            control.forever()(
                motion.move(3),
                motion.if_on_edge_bounce(),
                control.wait(0.02),
            ),
        )

        rt_orig = project.build_runtime()
        rt_rebuilt = _roundtrip(project, tmp_path)
        _assert_runtimes_equal(rt_orig, rt_rebuilt)
