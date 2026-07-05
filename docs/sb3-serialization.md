# SB3 Serialization Format

This document describes the Scratch 3.0 (`.sb3`) serialization format used by
py-scratch, focusing on the JSON project structure inside the ZIP archive.

## Overview

An `.sb3` file is a standard ZIP archive containing:

- `project.json` — the project data (targets, blocks, variables, costumes, sounds)
- Asset files — costume images (`.svg`, `.png`, `.jpg`) and sound files (`.wav`)

The `project.json` has this top-level structure:

```json
{
  "targets": [ /* stage, sprites */ ],
  "monitors": [],
  "extensions": [],
  "meta": {
    "semver": "3.0.0",
    "vm": "0.2.0",
    "agent": "py-scratch"
  }
}
```

## Target structure

Each target (stage or sprite) has:

```json
{
  "isStage": false,
  "name": "Sprite",
  "variables": { "var_id": ["name", value] },
  "lists": { "list_id": ["name", [items]] },
  "broadcasts": {},
  "blocks": { "block_id": { /* see below */ } },
  "currentCostume": 0,
  "costumes": [ /* see below */ ],
  "sounds": [ /* see below */ ],
  "volume": 100,
  "layerOrder": 0,
  "tempo": 60,
  "videoTransparency": 0.5,
  "videoState": "off"
}
```

Sprites additionally have:

```json
{
  "x": 0, "y": 0,
  "direction": 90,
  "size": 100,
  "visible": true,
  "rotationStyle": "all around",
  "draggable": false
}
```

## Block format

Every block is an object in `targets[].blocks{}` keyed by a unique string ID:

```json
"block_id": {
  "opcode": "motion_movesteps",
  "next": "next_block_id",
  "parent": "parent_block_id",
  "inputs": { "INPUT_NAME": [shadow_flag, value, ...] },
  "fields": { "FIELD_NAME": [value, id_or_null] },
  "shadow": false,
  "topLevel": false,
  "mutation": { /* see below */ },
  "x": null,
  "y": null
}
```

Key rules:

- **`topLevel: true`** — block is a hat block (starts a script). Has `x`, `y` for
  editor position.
- **`shadow: true`** — block is a shadow (dropdown, default value placeholder).
  Shadows are NOT visible in the editor, they fill unfilled inputs.
- **`parent`** — the block that contains this one (via an input or as the
  previous block in a chain).
- **`next`** — the next block in the sequential chain, or `null`.

## Input format

Inputs are arrays `[shadow_flag, value, ...]`.

### SHADOW_FLAG (1) — literal / compact primitive

```
[1, compact_primitive]
[1, raw_string]     // block ID string (e.g. custom_block)
```

Used for literal values and shadow inputs.  The value is either:

- A **compact primitive** `[type_code, string_value]` — see below.
- A **raw string** (block ID) — when the value is NOT a user-visible literal
  but a reference that happens to be a string (e.g. `custom_block` input on
  `procedures_definition`).

Note: `custom_block` on `procedures_definition` uses the raw string form
(not a compact primitive), even though it's a shadow.  The correct serialization
is `is_literal=False` with `shadow=True`.

### BLOCK_REF_FLAG (2) — block reference

```
[2, "referenced_block_id"]
```

Used when an input is connected to another block (reporter, stack).

### OBSOLETE_FLAG (3) — block reference with shadow default

```
[3, "block_id_or_null", compact_primitive]
```

Used for inputs that may either have a block connected (the block ID) or
show a default value (the compact primitive).  The Shadow DOM in the editor
uses this to show a default when the input is disconnected.

Note: despite the name "obsolete", this format is actively used for
`control_repeat` TIMES and `operator_divide` NUM1/NUM2 inputs in
officially-generated sb3 files.

### Compact primitive format

Values inside inputs are wrapped as compact primitives:

| Type code | Name | Example |
|-----------|------|---------|
| 4 | NUMBER | `[4, "42"]` |
| 5 | POSITIVE_NUMBER | `[5, "0.03"]` |
| 6 | WHOLE_NUMBER | `[6, "10"]` |
| 7 | INTEGER | `[7, "-5"]` |
| 8 | ANGLE | `[8, "90"]` |
| 9 | COLOUR_PICKER | `[9, "#ff0000"]` |
| 10 | TEXT | `[10, "hello"]` |
| 11 | BROADCAST | `[11, "message", "broadcast_id"]` |
| 12 | VARIABLE | `[12, "var_name", "var_id"]` |
| 13 | LIST | `[13, "list_name", "list_id"]` |

**All numeric values are stored as strings** inside the compact primitive,
even for type codes 4-8 (which represent numbers).  This is the Scratch format:
`Number(42)` becomes `[4, "42"]`, not `[4, 42]`.

## Variable inlining

When a `data_variable` reporter (e.g. `data.variable('score')`) is used as an
input to another block (e.g. `control.wait(data.variable('beat'))`), the
variable reference is **inlined** using OBSOLETE_FLAG (3) with a VARIABLE
compact primitive, instead of creating a separate `data_variable` block:

```json
{
  "opcode": "control_wait",
  "inputs": {
    "DURATION": [
      3,                           // OBSOLETE_FLAG
      [12, "beat", "e455efa7"],    // VARIABLE compact primitive (name, ID)
      [5, "1"]                     // POSITIVE_NUMBER shadow default
    ]
  }
}
```

The VARIABLE primitive's third element is the variable's UUID (matching the key
in `targets[].variables{}`).  This ID is resolved at serialization time by
`build_project_json()`, which builds a combined variable-name-to-ID map across
all targets (including the stage).

This inlining happens automatically in the DSL's `_resolve_inputs()` function
whenever a `Reporter` with `opcode='data_variable'` is passed as an input.
Non-variable reporters (e.g. `operators.add(...)`) continue to use
BLOCK_REF_FLAG (2).

## Procedure (custom block) format

Custom blocks have a special three-block structure:

### procedures_definition

```json
"def_id": {
  "opcode": "procedures_definition",
  "next": "first_body_block_id",
  "inputs": {
    "custom_block": [2, "proto_id"]   // BLOCK_REF_FLAG (2), NOT shadow
  },
  "topLevel": true
}
```

- The `custom_block` input uses **BLOCK_REF_FLAG (2)**, not SHADOW_FLAG (1).
- The definition block itself does NOT have a `mutation`.

### procedures_prototype

```json
"proto_id": {
  "opcode": "procedures_prototype",
  "parent": "def_id",
  "shadow": false,
  "topLevel": false,
  "inputs": {
    "arg_id_1": [2, "arg_reporter_1_id"],
    "arg_id_2": [2, "arg_reporter_2_id"]
  },
  "mutation": {
    "tagName": "mutation",
    "children": [],
    "proccode": "step %s %n",
    "argumentids": "[\"arg_id_1\", \"arg_id_2\"]",
    "argumentnames": "[\"dir\", \"px\"]",
    "argumentdefaults": "[0, 0]",
    "warp": "false"
  }
}
```

Key rules:

- **`shadow: false`** — the prototype is NOT a shadow block (despite being
  a "prototype").  It is a proper block that owns the argument reporters.
- **`inputs`** — each argument ID maps to its corresponding
  `argument_reporter_string_number` or `argument_reporter_boolean` block.
- **`mutation.proccode`** — the human-readable procedure signature with `%s`
  (string) and `%n` (number) placeholders.

### argument_reporter_string_number / argument_reporter_boolean

```json
"arg_reporter_id": {
  "opcode": "argument_reporter_string_number",
  "parent": "proto_id",
  "shadow": false,
  "fields": {
    "VALUE": ["param_name", null]
  }
}
```

- These are **owned by the prototype** (their `parent` is the prototype ID).
- The `VALUE` field holds the parameter name (e.g. `"dir"`, `"px"`).

### procedures_call

```json
"call_id": {
  "opcode": "procedures_call",
  "parent": "parent_block_id",
  "mutation": {
    "tagName": "mutation",
    "children": [],
    "proccode": "step %s %n",
    "argumentids": "[\"0\", \"1\"]",
    "warp": "false"
  },
  "inputs": {
    "0": [1, [10, "right"]],      // SHADOW_FLAG with TEXT primitive
    "1": [1, [10, "50"]]           // SHADOW_FLAG with TEXT primitive
  }
}
```

Key rules:

- **Argument inputs use SHADOW_FLAG (1)** with TEXT compact primitives.
  Even numeric arguments are serialized as `[10, "50"]` (TEXT), not `[4, 50]`
  (NUMBER).  The Scratch editor converts them at runtime based on the `%s`/`%n`
  placeholder in the proccode.
- **Argument IDs** in `mutation.argumentids` are sequential integer strings
  (`"0"`, `"1"`, ...) that match the argument IDs in the prototype's mutation.
  This allows the Scratch editor to map call arguments to definition parameters
  by position.
- The call mutation typically omits `argumentnames` and `argumentdefaults`
  (they are only present on the prototype).

## Reference implementation

The serialization is implemented in `scratch/sb3/serialize.py`:

- `serialize_block(block)` → JSON dict
- `serialize_input(inp)` → JSON array `[flag, value]`
- `serialize_field(fld)` → JSON array `[value, id]`
- `serialize_target(target)` → JSON dict
- `build_project_json(runtime)` → full `project.json` dict

The builder (`scratch/dsl/builder.py`) constructs proper procedure blocks
at build time in `Script.build()`, splitting `procedures_definition` into
the definition + prototype + argument_reporter structure when a mutation
is present.

Deserialization (reading sb3 → data model) is in `scratch/sb3/parse.py`:

- `parse_block(block_id, data)` → `Block`
- `parse_input(name, data)` → `Input`
- `parse_field(name, data)` → `Field`
- `parse_target(data)` → `Target`
- `load_project(path)` → `Runtime`
