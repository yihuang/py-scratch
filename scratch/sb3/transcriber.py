"""
Transcriber — decompile .sb3 files into py-scratch DSL Python source code.

Usage::

    from scratch.sb3.transcriber import transcribe_to_dir

    transcribe_to_dir('project.sb3')
    transcribe_to_dir('project.sb3', 'my_game')

This generates::

    game_src/               # ``<sb3_stem>_src/``
      main.py               # transcribed module
      assets/               # extracted images and sounds
        costume1.png
        sound1.wav
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

from scratch.sb3.io import load_project
from scratch.vm.target import Target
from scratch.vm.runtime import Runtime
from scratch.vm.types import Block, Input

# ── Opcode → DSL mapping ─────────────────────────────────────────────────────

# Each entry: (module_name, function_name) or None for unsupported
# The transcriber maps opcodes to DSL function calls.
# For opcodes not in this map, we emit a comment placeholder.

_DSL_MODULES = {
    # Motion
    'motion_movesteps': ('motion', 'move'),
    'motion_turnright': ('motion', 'turn_right'),
    'motion_turnleft': ('motion', 'turn_left'),
    'motion_gotoxy': ('motion', 'goto'),
    'motion_glidesecstoxy': ('motion', 'glide'),
    'motion_setx': ('motion', 'set_x'),
    'motion_sety': ('motion', 'set_y'),
    'motion_changexby': ('motion', 'change_x'),
    'motion_changeyby': ('motion', 'change_y'),
    'motion_ifonedgebounce': ('motion', 'if_on_edge_bounce'),
    'motion_setrotationstyle': ('motion', 'set_rotation_style'),
    'motion_setdirection': ('motion', 'set_direction'),
    'motion_pointindirection': ('motion', 'set_direction'),
    'motion_pointtowards': ('motion', 'point_towards'),
    'motion_goto': ('motion', 'goto'),  # goto dropdown
    'motion_glideto': ('motion', 'glide_to'),
    'motion_xposition': ('motion', 'x_position'),
    'motion_yposition': ('motion', 'y_position'),
    'motion_direction': ('motion', 'direction'),
    # Looks
    'looks_say': ('looks', 'say'),
    'looks_sayforsecs': ('looks', 'say_for_seconds'),
    'looks_think': ('looks', 'think'),
    'looks_thinkforsecs': ('looks', 'think_for_seconds'),
    'looks_show': ('looks', 'show'),
    'looks_hide': ('looks', 'hide'),
    'looks_switchcostumeto': ('looks', 'switch_costume_to'),
    'looks_nextcostume': ('looks', 'next_costume'),
    'looks_switchbackdropto': ('looks', 'switch_backdrop_to'),
    'looks_switchbackdroptoandwait': ('looks', 'switch_backdrop_to'),
    'looks_nextbackdrop': ('looks', 'next_backdrop'),
    'looks_changeeffectby': ('looks', 'change_effect'),
    'looks_seteffectto': ('looks', 'set_effect'),
    'looks_cleargraphiceffects': ('looks', 'clear_effects'),
    'looks_changesizeby': ('looks', 'change_size_by'),
    'looks_setsizeto': ('looks', 'set_size_to'),
    'looks_changevolumeby': ('looks', 'change_volume_by'),
    'looks_setvolumeto': ('looks', 'set_volume_to'),
    'looks_costumenumbername': ('looks', 'costume_number_name'),
    'looks_size': ('looks', 'size'),
    'looks_volume': ('looks', 'volume'),
    'looks_gotofrontback': ('looks', 'go_to_front_back'),
    'looks_goforwardbackwardlayers': ('looks', 'go_forward_backward_layers'),
    'looks_backdropnumbername': ('looks', 'backdrop_number_name'),
    # Sound — no dedicated DSL module yet; emit opcode-based placeholder
    'sound_play': ('looks', None),  # placeholder
    'sound_playuntildone': ('looks', None),
    'sound_stopallsounds': ('looks', None),
    'sound_setvolumeto': ('looks', 'set_volume_to'),
    'sound_changevolumeby': ('looks', 'change_volume_by'),
    'sound_volume': ('looks', 'volume'),
    'sound_seteffectto': ('looks', None),
    'sound_changeeffectby': ('looks', None),
    'sound_cleareffects': ('looks', None),
    'sound_settempo': ('looks', None),
    'sound_changetempo': ('looks', None),
    'sound_tempo': ('looks', None),
    # Events
    'event_whenflagclicked': ('events', 'when_flag_clicked'),
    'event_whenkeypressed': ('events', 'when_key_pressed'),
    'event_whenthisspriteclicked': ('events', 'when_this_sprite_clicked'),
    'event_whenbackdropswitchesto': ('events', 'when_backdrop_switches_to'),
    'event_whengreaterthan': ('events', 'when_greater_than'),
    'event_whenbroadcastreceived': ('events', 'when_broadcast_received'),
    'event_broadcast': ('events', 'broadcast'),
    'event_broadcastandwait': ('events', 'broadcast_and_wait'),
    # Control
    'control_repeat': ('control', 'repeat'),
    'control_forever': ('control', 'forever'),
    'control_if': ('control', 'if_'),
    'control_if_else': ('control', 'if_else'),
    'control_wait': ('control', 'wait'),
    'control_stop': ('control', 'stop'),
    'control_repeat_until': ('control', 'repeat_until'),
    'control_wait_until': ('control', 'wait_until'),
    'control_create_clone_of': ('control', 'create_clone_of'),
    'control_delete_this_clone': ('control', 'delete_this_clone'),
    'control_all_at_once': ('control', 'all_at_once'),
    'control_start_as_clone': ('control', 'when_start_as_clone'),
    # Data (variables)
    'data_setvariableto': ('data', 'set_variable'),
    'data_changevariableby': ('data', 'change_variable'),
    'data_showvariable': ('data', 'show_variable'),
    'data_hidevariable': ('data', 'hide_variable'),
    'data_variable': ('data', 'variable'),
    # Data (lists)
    'data_addtolist': ('data', 'add_to_list'),
    'data_deleteoflist': ('data', 'delete_of_list'),
    'data_insertatlist': ('data', 'insert_at_list'),
    'data_replaceitemoflist': ('data', 'replace_item_of_list'),
    'data_itemoflist': ('data', 'item_of_list'),
    'data_lengthoflist': ('data', 'length_of_list'),
    'data_listcontainsitem': ('data', 'list_contains_item'),
    'data_listcontents': ('data', 'list_contains_item'),  # list reporter
    # Operators
    'operator_add': ('operators', 'add'),
    'operator_subtract': ('operators', 'sub'),
    'operator_multiply': ('operators', 'mult'),
    'operator_divide': ('operators', 'div'),
    'operator_random': ('operators', 'random'),
    'operator_gt': ('operators', 'gt'),
    'operator_lt': ('operators', 'lt'),
    'operator_equals': ('operators', 'eq'),
    'operator_and': ('operators', 'and_'),
    'operator_or': ('operators', 'or_'),
    'operator_not': ('operators', 'not_'),
    'operator_join': ('operators', 'join'),
    'operator_letter_of': ('operators', 'letter_of'),
    'operator_length': ('operators', 'length'),
    'operator_contains': ('operators', 'contains'),
    'operator_mod': ('operators', 'mod'),
    'operator_round': ('operators', 'round_'),
    'operator_mathop': ('operators', '_mathop'),
    # Sensing
    'sensing_askandwait': ('sensing', 'ask_and_wait'),
    'sensing_resettimer': ('sensing', 'reset_timer'),
    'sensing_answer': ('sensing', 'answer'),
    'sensing_mousex': ('sensing', 'mouse_x'),
    'sensing_mousey': ('sensing', 'mouse_y'),
    'sensing_mousedown': ('sensing', 'mouse_down'),
    'sensing_keypressed': ('sensing', 'key_pressed'),
    'sensing_touchingobject': ('sensing', 'touching'),
    'sensing_touchingcolor': ('sensing', 'touching_color'),
    'sensing_coloristouchingcolor': ('sensing', 'color_is_touching_color'),
    'sensing_distanceto': ('sensing', 'distance_to'),
    'sensing_timer': ('sensing', 'timer'),
    'sensing_current': ('sensing', 'current'),
    'sensing_dayssince2000': ('sensing', 'days_since_2000'),
    'sensing_loudness': ('sensing', 'loudness'),
    'sensing_username': ('sensing', 'username'),
    # Pen
    'pen_penDown': ('pen', 'pen_down'),
    'pen_penUp': ('pen', 'pen_up'),
    'pen_penClear': ('pen', 'pen_clear'),
    'pen_stamp': ('pen', 'stamp'),
    'pen_changePenColorParamBy': ('pen', 'change_pen_color_by'),
    'pen_setPenColorParamTo': ('pen', 'set_pen_color_to'),
    'pen_changePenSizeBy': ('pen', 'change_pen_size_by'),
    'pen_setPenSizeTo': ('pen', 'set_pen_size_to'),
    'pen_setPenColorToColor': ('pen', 'pen_color'),
}

# Opcodes that take a SUBSTACK input (C-shaped)
_C_SHAPED_OPCODES = {
    'control_repeat',
    'control_forever',
    'control_if',
    'control_if_else',
    'control_repeat_until',
    'control_all_at_once',
}

# Opcodes that take SUBSTACK2 (else branch)
_HAS_ELSE_OPCODES = {'control_if_else'}

# Menu/field opcodes that should not be decompiled as top-level commands
_MENU_OPCODES = {
    'motion_pointtowards_menu',
    'motion_goto_menu',
    'motion_glideto_menu',
    'looks_costume',
    'looks_backdrops',
    'sound_sounds_menu',
    'sensing_of_object_menu',
    'data_variable_menu',
    'data_list_menu',
}

# ── Input name mapping: scratch input name → DSL parameter name ────────────

_INPUT_PARAM_MAP: dict[str, dict[str, str]] = {
    'motion_movesteps': {'STEPS': 'steps'},
    'motion_turnright': {'DEGREES': 'degrees'},
    'motion_turnleft': {'DEGREES': 'degrees'},
    'motion_gotoxy': {'X': 'x', 'Y': 'y'},
    'motion_glidesecstoxy': {'SECS': 'secs', 'X': 'x', 'Y': 'y'},
    'motion_setx': {'X': 'x'},
    'motion_sety': {'Y': 'y'},
    'motion_changexby': {'DX': 'dx'},
    'motion_changeyby': {'DY': 'dy'},
    'motion_setdirection': {'DIRECTION': 'direction'},
    'motion_pointindirection': {'DIRECTION': 'direction'},
    'looks_say': {'MESSAGE': 'message'},
    'looks_sayforsecs': {'MESSAGE': 'message', 'SECS': 'secs'},
    'looks_think': {'MESSAGE': 'message'},
    'looks_thinkforsecs': {'MESSAGE': 'message', 'SECS': 'secs'},
    'looks_changeeffectby': {'CHANGE': 'change'},
    'looks_seteffectto': {'VALUE': 'value'},
    'looks_changesizeby': {'CHANGE': 'change'},
    'looks_setsizeto': {'SIZE': 'size'},
    'looks_changevolumeby': {'VOLUME': 'change'},
    'looks_setvolumeto': {'VOLUME': 'volume'},
    'sound_setvolumeto': {'VOLUME': 'volume'},
    'sound_changevolumeby': {'VOLUME': 'change'},
    'sound_seteffectto': {'VALUE': 'value'},
    'sound_changeeffectby': {'VALUE': 'change'},
    'control_repeat': {'TIMES': 'times'},
    'control_wait': {'DURATION': 'duration'},
    'control_wait_until': {'CONDITION': 'condition'},
    'control_repeat_until': {'CONDITION': 'condition'},
    'data_setvariableto': {'VALUE': 'value'},
    'data_changevariableby': {'VALUE': 'change'},
    'data_addtolist': {'ITEM': 'item'},
    'data_deleteoflist': {'INDEX': 'index'},
    'data_insertatlist': {'INDEX': 'index', 'ITEM': 'item'},
    'data_replaceitemoflist': {'INDEX': 'index', 'ITEM': 'item'},
    'data_itemoflist': {'INDEX': 'index'},
    'data_listcontainsitem': {'ITEM': 'item'},
    'operator_add': {'NUM1': 'a', 'NUM2': 'b'},
    'operator_subtract': {'NUM1': 'a', 'NUM2': 'b'},
    'operator_multiply': {'NUM1': 'a', 'NUM2': 'b'},
    'operator_divide': {'NUM1': 'a', 'NUM2': 'b'},
    'operator_random': {'FROM': 'from_', 'TO': 'to'},
    'operator_gt': {'OPERAND1': 'a', 'OPERAND2': 'b'},
    'operator_lt': {'OPERAND1': 'a', 'OPERAND2': 'b'},
    'operator_equals': {'OPERAND1': 'a', 'OPERAND2': 'b'},
    'operator_and': {'OPERAND1': 'a', 'OPERAND2': 'b'},
    'operator_or': {'OPERAND1': 'a', 'OPERAND2': 'b'},
    'operator_not': {'OPERAND': 'a'},
    'operator_join': {'STRING1': 'a', 'STRING2': 'b'},
    'operator_letter_of': {'LETTER': 'letter', 'STRING': 'string'},
    'operator_length': {'STRING': 'string'},
    'operator_contains': {'STRING1': 'string', 'STRING2': 'substring'},
    'operator_mod': {'NUM1': 'a', 'NUM2': 'b'},
    'operator_round': {'NUM': 'n'},
    'operator_mathop': {'NUM': 'n'},
    'sensing_askandwait': {'QUESTION': 'question'},
    'sensing_touchingcolor': {'COLOR': 'color'},
    'sensing_coloristouchingcolor': {'COLOR': 'color', 'COLOR2': 'other_color'},
    'control_create_clone_of': {},  # field only
    'control_stop': {},  # field only
    'motion_glide': {'SECS': 'secs', 'X': 'x', 'Y': 'y'},
    'motion_goto': {},  # menu field
    'motion_glideto': {},  # menu field
    'motion_pointtowards': {},  # menu field
    'looks_switchcostumeto': {},  # field only
    'looks_switchbackdropto': {},  # field only
    'looks_switchbackdroptoandwait': {},  # field only
    'looks_gotofrontback': {},  # field only
    'looks_goforwardbackwardlayers': {'NUM': 'num'},
    'event_whenkeypressed': {},  # field only
    'event_whenbackdropswitchesto': {},  # field only
    'event_whengreaterthan': {},  # field + input
    'event_broadcast': {},  # field only
    'event_broadcastandwait': {},  # field only
    'event_whenbroadcastreceived': {},  # field only
    'sensing_keypressed': {},  # field/input
    'sensing_touchingobject': {},  # field/input
    'sensing_distanceto': {},  # field/input
    'pen_changePenColorParamBy': {'COLOR_PARAM': 'change'},
    'pen_setPenColorParamTo': {'COLOR_PARAM': 'color'},
    'pen_changePenSizeBy': {'SIZE': 'change'},
    'pen_setPenSizeTo': {'SIZE': 'size'},
    'pen_setPenColorToColor': {'COLOR': 'color'},
    'sensing_current': {},  # field
}

# ── Field-only opcodes (inputs come from field values, not input slots) ─────

_FIELD_ONLY_OPCODES = {
    'control_stop',  # STOP_OPTION field
    'control_create_clone_of',  # CLONE_OPTION field
    'motion_pointtowards',  # TOWARDS field
    'motion_goto',  # TO field
    'motion_glideto',  # TO field
    'motion_setrotationstyle',  # STYLE field
    'looks_switchcostumeto',  # COSTUME field
    'looks_switchbackdropto',  # BACKDROP field
    'event_whenkeypressed',  # KEY_OPTION field
    'event_whenbackdropswitchesto',  # BACKDROP field
    'event_whenbroadcastreceived',  # BROADCAST_OPTION field
    'event_broadcast',  # BROADCAST_OPTION field
    'event_broadcastandwait',  # BROADCAST_OPTION field
    'event_whengreaterthan',  # WHENGREATERTHAN_MENU field
    'sensing_current',  # CURRENTMENU field
    'looks_costumenumbername',  # NUMBER_NAME field
    'looks_backdropnumbername',  # NUMBER_NAME field
    'looks_gotofrontback',  # FRONT_BACK field
    'looks_goforwardbackwardlayers',  # FORWARD_BACKWARD field
    'sound_play',  # SOUND_MENU
    'sound_playuntildone',  # SOUND_MENU
}

# ── Field name → DSL keyword argument mapping ──────────────────────────────

_FIELD_PARAM_MAP: dict[str, dict[str, str]] = {
    'control_stop': {'STOP_OPTION': 'option'},
    'control_create_clone_of': {'CLONE_OPTION': 'sprite'},
    'motion_pointtowards': {'TOWARDS': 'towards'},
    'motion_goto': {'TO': 'to'},
    'motion_glideto': {'TO': 'to'},
    'motion_setrotationstyle': {'STYLE': 'style'},
    'looks_switchcostumeto': {'COSTUME': 'costume'},
    'looks_switchbackdropto': {'BACKDROP': 'backdrop'},
    'looks_switchbackdroptoandwait': {'BACKDROP': 'backdrop'},
    'looks_gotofrontback': {'FRONT_BACK': 'front_back'},
    'event_whenkeypressed': {'KEY_OPTION': 'key'},
    'event_whenbackdropswitchesto': {'BACKDROP': 'backdrop'},
    'event_whenbroadcastreceived': {'BROADCAST_OPTION': 'message'},
    'event_broadcast': {'BROADCAST_OPTION': 'message'},
    'event_broadcastandwait': {'BROADCAST_OPTION': 'message'},
    'event_whengreaterthan': {'WHENGREATERTHAN_MENU': 'metric'},
    'sensing_keypressed': {'KEY_OPTION': 'key'},
    'sensing_touchingobject': {'TOUCHINGOBJECTMENU': 'object'},
    'sensing_distanceto': {'DISTANCETOMENU': 'object'},
    'sensing_current': {'CURRENTMENU': 'unit'},
    'looks_costumenumbername': {'NUMBER_NAME': 'number_name'},
    'looks_backdropnumbername': {'NUMBER_NAME': 'number_name'},
    'looks_changeeffectby': {'EFFECT': 'effect'},
    'looks_seteffectto': {'EFFECT': 'effect'},
    'sound_seteffectto': {'EFFECT': 'effect'},
    'sound_changeeffectby': {'EFFECT': 'effect'},
    'looks_goforwardbackwardlayers': {'FORWARD_BACKWARD': 'forward_backward'},
    'sound_play': {'SOUND_MENU': 'sound'},
    'sound_playuntildone': {'SOUND_MENU': 'sound'},
}


# ── Field values that must be positional args (not kwargs) ──────────────

_FIELD_POSITIONAL_ARGS: dict[str, list[tuple[str, str]]] = {
    'data_setvariableto': [('VARIABLE', 'variable')],
    'data_changevariableby': [('VARIABLE', 'variable')],
    'data_showvariable': [('VARIABLE', 'variable')],
    'data_hidevariable': [('VARIABLE', 'variable')],
    'data_variable': [('VARIABLE', 'variable')],
    'data_addtolist': [('LIST', 'list_')],
    'data_deleteoflist': [('LIST', 'list_')],
    'data_insertatlist': [('LIST', 'list_')],
    'data_replaceitemoflist': [('LIST', 'list_')],
    'data_itemoflist': [('LIST', 'list_')],
    'data_lengthoflist': [('LIST', 'list_')],
    'data_listcontainsitem': [('LIST', 'list_')],
    'looks_changeeffectby': [('EFFECT', 'effect')],
    'looks_seteffectto': [('EFFECT', 'effect')],
    'sound_seteffectto': [('EFFECT', 'effect')],
    'sound_changeeffectby': [('EFFECT', 'effect')],
    'looks_goforwardbackwardlayers': [('FORWARD_BACKWARD', 'forward_backward')],
}


# ── Hat opcode → DSL hat function mapping ──────────────────────────────────

_HAT_OPCODES: dict[str, tuple[str, str]] = {
    'event_whenflagclicked': ('events', 'when_flag_clicked'),
    'event_whenkeypressed': ('events', 'when_key_pressed'),
    'event_whenthisspriteclicked': ('events', 'when_this_sprite_clicked'),
    'event_whenbackdropswitchesto': ('events', 'when_backdrop_switches_to'),
    'event_whengreaterthan': ('events', 'when_greater_than'),
    'event_whenbroadcastreceived': ('events', 'when_broadcast_received'),
    'control_start_as_clone': ('control', 'when_start_as_clone'),
}

# ── Python-safe name sanitizer ─────────────────────────────────────────────

_RESERVED = frozenset(
    {
        'False',
        'None',
        'True',
        'and',
        'as',
        'assert',
        'async',
        'await',
        'break',
        'class',
        'continue',
        'def',
        'del',
        'elif',
        'else',
        'except',
        'finally',
        'for',
        'from',
        'global',
        'if',
        'import',
        'in',
        'is',
        'lambda',
        'nonlocal',
        'not',
        'or',
        'pass',
        'raise',
        'return',
        'try',
        'while',
        'with',
        'yield',
    }
)


def _safe_name(name: str) -> str:
    """Convert a Scratch name to a valid Python identifier."""
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if not safe or safe[0].isdigit():
        safe = f'_{safe}'
    if safe in _RESERVED:
        safe = f'{safe}_'
    return safe


# ── Main transcription entry point ──────────────────────────────────────────


def transcribe_to_dir(
    sb3_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    py_filename: str = 'main.py',
    asset_dir_name: str = 'assets',
) -> None:
    """Decompile an .sb3 file into a py-scratch DSL Python file.

    Generates::

        output_dir/
          main.py              # transcribed module
          assets/              # extracted images and sounds

    Run with::

        python output_dir/main.py

    Args:
        sb3_path: Path to the .sb3 file.
        output_dir: Output directory (default: ``<sb3_stem>_src/``).
        py_filename: Name of the generated Python file (default: ``main.py``).
        asset_dir_name: Name of the assets directory (default: ``assets``).
    """
    sb3_path = Path(sb3_path)

    if output_dir is None:
        output_dir = sb3_path.with_suffix('').with_name(sb3_path.stem + '_src')
    output_dir = Path(output_dir)

    asset_dir = output_dir / asset_dir_name
    output_py = output_dir / py_filename

    # Load the project
    rt = load_project(str(sb3_path))

    output_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)

    # Extract all assets from the zip
    _extract_assets(sb3_path, asset_dir)

    lines = _generate_source(rt, asset_dir)
    output_py.write_text('\n'.join(lines))
    print(f'  {output_py.resolve()}')
    print(f'  assets: {asset_dir.resolve()}')


# Backward-compat alias
transcribe_to_file = transcribe_to_dir


# ── Asset extraction ────────────────────────────────────────────────────────


def _extract_assets(sb3_path: str | Path, asset_dir: Path) -> None:
    """Extract asset files from the sb3 zip to asset_dir."""
    with zipfile.ZipFile(str(sb3_path)) as zf:
        for name in zf.namelist():
            if name == 'project.json':
                continue
            data = zf.read(name)
            (asset_dir / name).write_bytes(data)


def _generate_source(rt: Runtime, asset_dir: Path) -> list[str]:
    """Generate py-scratch source code at module level, like the hand-written examples."""
    lines: list[str] = []
    indent = ''

    # Collect all opcodes across all targets
    all_opcodes: set[str] = set()
    for tgt in rt.targets:
        for block in tgt.blocks.values():
            if block.opcode in _MENU_OPCODES:
                continue
            mapping = _DSL_MODULES.get(block.opcode)
            if mapping:
                mod_name, _ = mapping
                all_opcodes.add(mod_name)

    # Find project name from first non-stage target, or use "Project"
    project_name = 'Project'
    for tgt in rt.targets:
        if not tgt.is_stage:
            project_name = tgt.name
            break

    lines.append('#!/usr/bin/env python3')
    lines.append('"""Auto-transcribed Scratch project."""')
    lines.append('')
    lines.append('from __future__ import annotations')
    lines.append('')
    _add_dsl_imports(lines, all_opcodes)
    lines.append('')
    lines.append('')
    lines.append(f'project = Project({_format_literal(project_name)})')
    lines.append('')

    for tgt in rt.targets:
        target_var = 'stage' if tgt.is_stage else _safe_name(tgt.name)

        if tgt.is_stage:
            lines.append('# --- Stage --------------------------------------------------')
            lines.append('stage = project.stage')
        else:
            lines.append(f'# --- Sprite: {tgt.name} ----------------------------------------')
            lines.append(f'{target_var} = project.sprite({_format_literal(tgt.name)})')

        # Variables
        _emit_variables(lines, indent, tgt, target_var)
        # Lists
        _emit_lists(lines, indent, tgt, target_var)
        # Costumes
        _emit_costumes(lines, indent, tgt, target_var)
        # Sounds
        _emit_sounds(lines, indent, tgt, target_var)

        # Sprite properties
        if not tgt.is_stage:
            _emit_sprite_props(lines, indent, tgt, target_var)
        # Stage properties
        if tgt.is_stage:
            _emit_stage_props(lines, indent, tgt, target_var)

        # Scripts
        _emit_scripts(lines, indent, tgt, target_var)

    lines.append('')
    lines.append('')
    lines.append('if __name__ == "__main__":')
    lines.append('    import argparse')
    lines.append('')
    lines.append('    parser = argparse.ArgumentParser(description=__doc__)')
    lines.append('    parser.add_argument("--save", "-o", type=str, help="Save project to .sb3 file")')
    lines.append('    args = parser.parse_args()')
    lines.append('')
    lines.append('    if args.save:')
    lines.append('        project.save(args.save)')
    lines.append('        print(f"Saved to {args.save}")')
    lines.append('    else:')
    lines.append('        rt = project.build_runtime()')
    lines.append('        from scratch.vm.renderer import Renderer')
    lines.append('        renderer = Renderer(rt, title=project.name)')
    lines.append('        renderer.run()')
    lines.append('')
    return lines


# ── Import generation ──────────────────────────────────────────────────────


def _add_dsl_imports(lines: list[str], used: set[str]) -> None:
    """Add DSL import lines for the used modules."""
    if not used:
        lines.append('from scratch.dsl import Project')
        return

    cats = []
    for c in sorted(used):
        cats.append(c)

    lines.append(f'from scratch.dsl import Project, {", ".join(cats)}')


# ── Variables & lists ──────────────────────────────────────────────────────


def _emit_variables(lines: list[str], indent: str, tgt: Target, target_var: str) -> None:
    """Emit variable declarations with their initial values."""
    if not tgt.variables:
        return
    lines.append('')
    lines.append(f'{indent}# ── Variables ─────────────────────────────────────')
    for var_id, var in tgt.variables.items():
        val = _format_literal(var.value)
        lines.append(f'{indent}{target_var}.var("{var.name}", {val})')


def _emit_lists(lines: list[str], indent: str, tgt: Target, target_var: str) -> None:
    """Emit list declarations as comments (no ``list()`` DSL API yet)."""
    if not tgt.lists:
        return
    lines.append('')
    lines.append(f'{indent}# --- Lists (not yet supported in DSL) ---')
    for lst_id, lst in tgt.lists.items():
        items = lst.contents
        if items:
            formatted = ', '.join(str(v) for v in items)
            lines.append(f'{indent}#   {target_var} list "{lst.name}": [{formatted}]')
        else:
            lines.append(f'{indent}#   {target_var} list "{lst.name}": []')


# ── Costumes & sounds ──────────────────────────────────────────────────────


def _emit_costumes(lines: list[str], indent: str, tgt: Target, target_var: str) -> None:
    """Emit costume declarations."""
    if not tgt.costumes:
        return
    lines.append('')
    lines.append(f'{indent}# --- Costumes / backdrops ----------------------------------')
    for i, c in enumerate(tgt.costumes):
        lines.append(f'{indent}{target_var}.costume("{c.name}")')
        lines.append(f'{indent}#   asset: {c.md5ext}')


def _emit_sounds(lines: list[str], indent: str, tgt: Target, target_var: str) -> None:
    """Emit sound declarations (sound_add for the target)."""
    if not tgt.sounds:
        return
    lines.append('')
    lines.append(f'{indent}# ── Sounds ────────────────────────────────────────────')
    for s in tgt.sounds:
        lines.append(f'{indent}#   sound: {s.name} ({s.md5ext})')
        # Note: scratch.dsl doesn't have a sound API yet, emit comments


# ── Sprite properties ──────────────────────────────────────────────────────


def _emit_sprite_props(lines: list[str], indent: str, tgt: Target, target_var: str) -> None:
    """Emit sprite position/direction/size/visibility assignment."""
    has_props = False
    if tgt.x != 0 or tgt.y != 0:
        lines.append(f'{indent}{target_var}.x = {tgt.x}')
        lines.append(f'{indent}{target_var}.y = {tgt.y}')
        has_props = True
    if tgt.direction != 90:
        lines.append(f'{indent}{target_var}.direction = {tgt.direction}')
        has_props = True
    if tgt.size != 100:
        lines.append(f'{indent}{target_var}.size = {tgt.size}')
        has_props = True
    if not tgt.visible:
        lines.append(f'{indent}{target_var}.visible = False')
        has_props = True
    if tgt.rotation_style != 'all around':
        lines.append(f'{indent}{target_var}.rotation_style = "{tgt.rotation_style}"')
        has_props = True
    if tgt.layer_order != 1:
        lines.append(f'{indent}{target_var}.layer_order = {tgt.layer_order}')
        has_props = True
    if has_props:
        pass  # newline already handled


def _emit_stage_props(lines: list[str], indent: str, tgt: Target, target_var: str) -> None:
    """Emit stage-specific properties."""
    if tgt.tempo != 60:
        lines.append(f'{indent}{target_var}.tempo = {tgt.tempo}')


# ── Script decompilation ───────────────────────────────────────────────────


def _emit_scripts(lines: list[str], indent: str, tgt: Target, target_var: str) -> None:
    """Decompile all hat+script chains into DSL method calls."""
    # Find all top-level hat blocks
    hat_chains: list[tuple[Block, list[dict[str, Any]]]] = []

    for bid, block in tgt.blocks.items():
        if not block.top_level:
            continue
        if block.opcode in _MENU_OPCODES:
            continue
        if block.opcode not in _HAT_OPCODES:
            continue

        # Decompile the chain starting from this hat's next block
        body_exprs = _decompile_chain(tgt, block.next) if block.next else []
        hat_chains.append((block, body_exprs))

    if not hat_chains:
        return

    lines.append('')
    lines.append(f'{indent}# ── Scripts ─────────────────────────────────────────')

    for hat_block, body_exprs in hat_chains:
        hat_mod, hat_func = _HAT_OPCODES[hat_block.opcode]

        # Build hat arguments from fields
        hat_args = _build_hat_args(hat_block)

        if body_exprs:
            body_indent = f'{indent}    '
            body_lines = []
            for expr in body_exprs:
                body_lines.extend(_format_body_lines(expr, body_indent))
            body_text = '\n'.join(body_lines)

            # Hat blocks that take body directly vs via __call__
            if hat_block.opcode == 'event_whenkeypressed':
                # when_key_pressed returns a callable: .when_key_pressed(key)(body)
                lines.append(f'{indent}{target_var}.{hat_func}({hat_args})(')
                lines.append(f'{body_text}')
                lines.append(f'{indent})')
            else:
                # Direct body: .when_flag_clicked(body)
                lines.append(f'{indent}{target_var}.{hat_func}(')
                lines.append(f'{body_text}')
                lines.append(f'{indent})')
        else:
            if hat_block.opcode == 'event_whenkeypressed':
                lines.append(f'{indent}# {target_var}.{hat_func}({hat_args})(...)')
            else:
                lines.append(f'{indent}# {target_var}.{hat_func}(...)  # (empty script)')


def _build_hat_args(hat_block: Block) -> str:
    """Build the argument string for a hat block based on its fields/inputs."""
    opcode = hat_block.opcode
    if opcode == 'event_whenkeypressed':
        key = _get_field_value(hat_block, 'KEY_OPTION', 'space')
        return _format_literal(key)
    elif opcode == 'event_whenbackdropswitchesto':
        bd = _get_field_value(hat_block, 'BACKDROP', 'next backdrop')
        return _format_literal(bd)
    elif opcode == 'event_whengreaterthan':
        metric = _get_field_value(hat_block, 'WHENGREATERTHAN_MENU', 'loudness')
        return f'metric={_format_literal(metric)}, value=...'  # simplified
    elif opcode == 'event_whenbroadcastreceived':
        msg = _get_field_value(hat_block, 'BROADCAST_OPTION', '')
        return _format_literal(msg)
    return ''


def _decompile_chain(tgt: Target, start_bid: str | None) -> list[dict[str, Any]]:
    """Walk a block chain from start_bid and produce expression dicts."""
    exprs: list[dict[str, Any]] = []
    bid = start_bid
    while bid and bid in tgt.blocks:
        block = tgt.blocks[bid]
        if block.opcode in _MENU_OPCODES:
            bid = block.next
            continue
        expr = _decompile_block(tgt, block)
        exprs.append(expr)
        bid = block.next
    return exprs


def _decompile_block(tgt: Target, block: Block) -> dict[str, Any]:
    """Decompile a single block into an expression dict.

    Returns::
        {'kind': 'call', 'opcode': '...', 'mod': 'motion', 'func': 'move',
         'args': [...], 'kwargs': {...},
         'body': [...] | None,  # for C-shaped blocks
         'body2': [...] | None,  # for if_else else branch
        }
        or
        {'kind': 'reporter', 'opcode': '...', ...}
        or
        {'kind': 'raw', 'code': '...'}  # fallback
    """
    opcode = block.opcode

    # Handle special blocks
    if opcode == 'data_variable':
        var_name = _resolve_variable_name(tgt, block)
        return {
            'kind': 'reporter',
            'opcode': opcode,
            'code': f'data.variable({_format_literal(var_name)})',
        }

    if opcode == 'data_listcontents':
        lst_name = _resolve_list_name(tgt, block)
        return {
            'kind': 'reporter',
            'opcode': opcode,
            'code': f'data.list_contains_item({_format_literal(lst_name)}, ...)',
        }

    if opcode == 'operator_mathop':
        op_name = _get_field_value(block, 'OPERATOR', 'sqrt')
        if op_name in ('sqrt', 'abs', 'floor', 'ceil', 'sin', 'cos', 'tan', 'asin', 'acos', 'atan'):
            func_name_map = {
                'sqrt': 'sqrt',
                'abs': 'abs_',
                'floor': 'floor_',
                'ceil': 'ceil_',
                'sin': 'sin',
                'cos': 'cos',
                'tan': 'tan',
                'asin': 'asin',
                'acos': 'acos',
                'atan': 'atan',
            }
            dsl_func = func_name_map.get(op_name, 'sqrt')
            return {
                'kind': 'reporter',
                'opcode': opcode,
                'mod': 'operators',
                'func': dsl_func,
                'args': _build_input_args(tgt, block),
            }

    # Look up the DSL mapping
    mapping = _DSL_MODULES.get(opcode)
    if mapping is None:
        return {'kind': 'comment', 'text': f'# TODO: {opcode}'}

    mod_name, func_name = mapping
    if func_name is None:
        return {'kind': 'comment', 'text': f'# TODO: {opcode} (no DSL function)'}

    # Check if this is a C-shaped block
    is_c_shaped = opcode in _C_SHAPED_OPCODES
    has_else = opcode in _HAS_ELSE_OPCODES

    field_pos = _get_field_positional_args(block)
    args = field_pos + _build_input_args(tgt, block)
    kwargs = _build_field_args(block, opcode)

    expr: dict[str, Any] = {
        'kind': 'call',
        'opcode': opcode,
        'mod': mod_name,
        'func': func_name,
        'args': args,
        'kwargs': kwargs,
        'body': None,
        'body2': None,
    }

    # Handle substack for C-shaped blocks
    if is_c_shaped:
        substack_id = _get_input_block_id(block, 'SUBSTACK')
        if substack_id:
            expr['body'] = _decompile_chain(tgt, substack_id)
        if has_else:
            else_id = _get_input_block_id(block, 'SUBSTACK2')
            if else_id:
                expr['body2'] = _decompile_chain(tgt, else_id)

    return expr


def _build_input_args(tgt: Target, block: Block) -> list[dict[str, str] | str]:
    """Build the positional argument list from a block's inputs."""
    if not block.inputs:
        return []

    opcode = block.opcode
    param_map = _INPUT_PARAM_MAP.get(opcode, {})

    # Collect named input values
    result: list[dict[str, str] | str] = []
    for iname, inp in block.inputs.items():
        if iname in ('SUBSTACK', 'SUBSTACK2'):
            continue
        param_name = param_map.get(iname, iname.lower())
        val_str = _format_input_value(tgt, inp, block)
        result.append({'name': param_name, 'value': val_str})

    return result


def _build_field_args(block: Block, opcode: str | None = None) -> dict[str, str]:
    """Build keyword argument dict from a block's fields.

    Skips fields that are already handled as positional args
    (see ``_FIELD_POSITIONAL_ARGS``).
    """
    if not block.fields:
        return {}

    if opcode is None:
        opcode = block.opcode

    param_map = _FIELD_PARAM_MAP.get(opcode, {})

    skip_fields: set[str] = set()
    for fld_name, _ in _FIELD_POSITIONAL_ARGS.get(opcode, []):
        skip_fields.add(fld_name)

    kwargs: dict[str, str] = {}
    for fname, fld in block.fields.items():
        if fname in skip_fields:
            continue
        param_name = param_map.get(fname, fname.lower())
        val = fld.value
        if isinstance(val, str):
            kwargs[param_name] = _format_literal(val)
        elif isinstance(val, (int, float)):
            kwargs[param_name] = str(val)
        else:
            kwargs[param_name] = repr(val)

    return kwargs


def _get_field_positional_args(block: Block) -> list[dict[str, str]]:
    """Extract field values that should be positional args.

    Returns a list of ``{'name': dsl_param, 'value': formatted_literal}``
    for fields listed in ``_FIELD_POSITIONAL_ARGS``.
    """
    opcode = block.opcode
    result: list[dict[str, str]] = []
    for fld_name, dsl_param in _FIELD_POSITIONAL_ARGS.get(opcode, []):
        fld = block.fields.get(fld_name) if block.fields else None
        if fld is None:
            continue
        val = fld.value
        formatted = _format_literal(val) if isinstance(val, (str, int, float)) else repr(val)
        result.append({'name': dsl_param, 'value': formatted})
    return result


def _get_input_block_id(block: Block, input_name: str) -> str | None:
    """Get the block ID referenced by an input (SUBSTACK, etc.)."""
    if not block.inputs:
        return None
    inp = block.inputs.get(input_name)
    if inp is None:
        return None
    if inp.shadow or inp.is_literal:
        return None
    return str(inp.value) if inp.value is not None else None


def _get_field_value(block: Block, field_name: str, default: Any = '') -> Any:
    """Get the string value from a field."""
    if block.fields and field_name in block.fields:
        return block.fields[field_name].value
    return default


def _format_input_value(tgt: Target, inp: Input, parent_block: Block) -> str:
    """Format an input value as a Python literal or reporter expression."""
    value = inp.value

    # Unwrap compact primitive arrays [type_code, actual_value]
    if isinstance(value, (list, tuple)) and len(value) == 2:
        _, value = value

    if inp.is_literal:
        return _format_literal(value)
    if inp.shadow:
        return _format_literal(value) if value is not None else '0'
    # It's a block reference
    bid = str(value)
    if bid in tgt.blocks:
        ref_block = tgt.blocks[bid]
        expr_dict = _decompile_block(tgt, ref_block)
        if expr_dict['kind'] == 'reporter':
            return str(expr_dict['code'])
        elif expr_dict['kind'] == 'call':
            return str(_format_call_expr(expr_dict, True))
        elif expr_dict['kind'] == 'raw':
            return str(expr_dict['code'])
        elif expr_dict['kind'] == 'comment':
            return str(expr_dict['text'])
    return repr(value)


def _format_literal(value: Any) -> str:
    """Format a literal value as Python source."""
    if value is None:
        return '0'
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Format without unnecessary decimals
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f'{value!r}'
    if isinstance(value, str):
        # Use single quotes for cleanliness
        escaped = value.replace("'", "\\'")
        return f"'{escaped}'"
    return repr(value)


def _format_call_expr(expr: dict[str, Any], inline: bool = False) -> str:
    """Format a call expression dict as Python source.

    With inline=True, produces a single line (for use inside another expression).
    """
    # Build positional args string
    arg_parts: list[str] = []
    for arg in expr.get('args', []):
        if isinstance(arg, dict):
            arg_parts.append(arg['value'])
        else:
            arg_parts.append(arg)

    # Build keyword args
    kwargs = expr.get('kwargs', {})
    for k, v in kwargs.items():
        arg_parts.append(f'{k}={v}')

    args_str = ', '.join(arg_parts)
    func_name = expr.get('func', '???')
    mod_name = expr.get('mod', '???')

    base = f'{mod_name}.{func_name}({args_str})'

    # Handle C-shaped blocks with body
    body = expr.get('body')
    body2 = expr.get('body2')

    if inline or (body is None and body2 is None):
        return base

    # Multi-line C-shaped call
    # This is handled differently — the hat method call wraps the whole thing
    return base


def _format_body_lines(expr: dict[str, Any], indent: str) -> list[str]:
    """Format a block expression into source lines for a body.

    Each expression's last line is terminated with `,` so callers can join
    multiple body items without explicit separators.
    """
    kind = expr.get('kind', '')

    if kind == 'comment':
        line = f'{indent}{expr["text"]}'
        return [line] if line.rstrip().endswith(',') else [f'{line},']

    if kind == 'call':
        func_name = expr.get('func', '???')
        mod_name = expr.get('mod', '???')

        arg_parts: list[str] = []
        for arg in expr.get('args', []):
            if isinstance(arg, dict):
                arg_parts.append(arg['value'])
            else:
                arg_parts.append(arg)
        for k, v in expr.get('kwargs', {}).items():
            arg_parts.append(f'{k}={v}')
        args_str = ', '.join(arg_parts)

        func_call = f'{mod_name}.{func_name}({args_str})'

        body = expr.get('body')
        body2 = expr.get('body2')

        if body is not None:
            inner_indent = indent + '    '
            body_lines = []
            for be in body:
                body_lines.extend(_format_body_lines(be, inner_indent))

            if body2 is not None:
                else_lines = []
                for be in body2:
                    else_lines.extend(_format_body_lines(be, inner_indent))
                else_text = '\n'.join(else_lines)
                body_text = '\n'.join(body_lines)
                return [
                    f'{indent}{func_call}(',
                    f'{body_text}',
                    f'{indent}).else_(',
                    f'{else_text}',
                    f'{indent}),',
                ]
            else:
                body_text = '\n'.join(body_lines)
                return [
                    f'{indent}{func_call}(',
                    f'{body_text}',
                    f'{indent}),',
                ]

        return [f'{indent}{func_call},']

    if kind == 'raw':
        return [f'{indent}{expr["code"]},']

    if kind == 'reporter':
        return [f'{indent}{expr["code"]},  # reporter']

    return [f'{indent}# unknown expression: {expr},']


# ── Variable/list name resolution ──────────────────────────────────────────


def _resolve_variable_name(tgt: Target, block: Block) -> str:
    """Resolve a VARIABLE field to the variable name."""
    if block.fields and 'VARIABLE' in block.fields:
        fld = block.fields['VARIABLE']
        # Try id first, then value
        if fld.id and fld.id in tgt.variables:
            return tgt.variables[fld.id].name
        return str(fld.value)
    return 'var'


def _resolve_list_name(tgt: Target, block: Block) -> str:
    """Resolve a LIST field to the list name."""
    if block.fields and 'LIST' in block.fields:
        fld = block.fields['LIST']
        if fld.id and fld.id in tgt.lists:
            return tgt.lists[fld.id].name
        return str(fld.value)
    return 'list'
