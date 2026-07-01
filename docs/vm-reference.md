# Scratch VM Architecture Reference

## 1. Key Data Structures

### Block

A node in the block tree. Blocks form a **linked list** via `next`/`parent` for sequential execution, and reference child blocks (reporters, substacks) through `inputs`.

| Field | Type | Meaning |
|-------|------|---------|
| `id` | `str` | Unique block identifier (UUID in SB3). |
| `opcode` | `str` | Maps to handler function (e.g. `motion_movesteps`). |
| `next` | `str | None` | Block ID of next block in the chain; `None` = end of script. |
| `parent` | `str | None` | Block ID of the containing block (the one whose input or substack this block fills). |
| `inputs` | `dict[str, Input]` | Named input slots — values, reporter references, or substacks. |
| `fields` | `dict[str, Field]` | Named field slots — dropdown selections, variable pickers, etc. |
| `shadow` | `bool` | Whether this is a shadow block (editor placeholder / menu block). |
| `top_level` | `bool` | Whether this block sits directly on the editor canvas (hat blocks, loose blocks). |
| `mutation` | `Mutation | None` | Procedure metadata (proccode, argument ids/names/defaults, warp). |
| `x`, `y` | `float | None` | Editor position (top-level blocks only). |

> **Why "hat"?** Hat blocks have a rounded top in the editor, shaped like a hat. Stack blocks snap into the notch below, like a head under a hat. The term is used throughout the VM: `startHats()`, `getHats()`, `edgeActivatedHats`. In JSON, hats have `"topLevel": true`.

**Block tree structure:**

```
event_whenflagclicked (top_level, hat)
  next → control_repeat
           inputs.SUBSTACK → motion_movesteps
                                next → motion_ifonedgebounce
           inputs.TIMES → math_number (shadow, value=10)
```

### Input

Represents a value plugged into a block's input slot.

| Field | Type | Meaning |
|-------|------|---------|
| `name` | `str` | Logical slot name (e.g. `STEPS`, `CONDITION`, `SUBSTACK`). |
| `value` | `Any` | The raw value: literal, block ID string, or inlined primitive `[type_code, ...]`. |
| `shadow` | `bool` | Whether the block in this slot is a shadow (editor placeholder). |

**SB3 JSON encoding:**

| Format | Meaning |
|--------|---------|
| `[1, literal]` | Shadow with literal value (number/string/bool). |
| `[1, [type_code, value, ...]]` | Shadow with **inlined primitive** — the shadow block is serialized inline. |
| `[2, block_id]` | Reference to another block (reporter) — no shadow. |
| `[3, literal, block_id]` | Obsolete: shadow + block reference (literal is the shadow's default). |

### Field

Represents a dropdown/field on a block (variable name, operator choice, etc.).

| Field | Type | Meaning |
|-------|------|---------|
| `name` | `str` | Field name (e.g. `VARIABLE`, `EFFECT`, `STYLE`). |
| `value` | `Any` | The selected value. |
| `variable_type` | `str | None` | `''` for broadcast, `'list'` for list, `'scalar'` for variable. |
| `id` | `str | None` | Variable/list/broadcast ID (for cross-referencing). |

### Mutation

Procedure metadata carried on `procedures_definition` and `procedures_call` blocks.

| Field | Type | Meaning |
|-------|------|---------|
| `tag_name` | `str` | Always `'mutation'`. |
| `proccode` | `str` | Procedure signature (e.g. `"myBlock %n %s"`). |
| `argumentids` | `str` | JSON array of argument UUIDs. |
| `argumentnames` | `str` | JSON array of argument display names. |
| `argumentdefaults` | `str` | JSON array of default values. |
| `warp` | `str` | `"true"` = run without screen refresh (warp mode). |
| `prototype` | `str | None` | Block ID of the `procedures_prototype` block (definition only). |

### Thread

One execution path, represented as a stack of frames with a generator at each level.

| Field | Type | Meaning |
|-------|------|---------|
| `target` | `Target` | The sprite/stage this thread runs on. |
| `top_block` | `str` | First block ID when the thread starts. |
| `status` | `str` | `RUNNING` / `WAITING` / `DONE`. |
| `stack` | `list[Frame]` | Call stack of frames. |
| `at_top` | `bool` | True after a fresh start. |

### Frame

One level of block execution on a thread's stack.

| Field | Type | Meaning |
|-------|------|---------|
| `block_id` | `str` | Block currently executing at this frame level. |
| `gen` | `Generator \| None` | Live Python generator for this block's handler; `None` if not started yet. |
| `status` | `str` | `'active'` or `'paused'`. |
| `result` | `Any` | Reporter result (when this frame evaluates a reporter). |
| `substack_pc` | `int` | Sub-stack position for control blocks (repeat, for-each). |
| `loop_count` | `int` | Loop iteration counter. |
| `saved` | `dict[str, Any]` | Handler-internal scratchpad (`_result` for reporter values, procedure arg values). |

### Target (Sprite or Stage)

A dataclass representing either a **sprite** or the **stage** (distinguished by `is_stage`).

| Category | Fields |
|----------|--------|
| **Blocks** | `blocks: dict[str, Block]` — block tree keyed by block ID. |
| **Data** | `variables`, `lists`, `broadcasts` — per-target mutable data stores. |
| **Visual** | `costumes`, `costume_index`, `sounds`, `visible`, `volume`, `layer_order`, `effects`. |
| **Motion** | `_x`, `_y`, `_direction`, `size`, `rotation_style` (sprites only). |
| **Pen** | `pen_down`, `pen_color`, `pen_size`, `pen_saturation`, `pen_brightness`. |
| **Bubble** | `say_text`, `say_until` — speech bubble state. |
| **Meta** | `_hat_cache` — lazy dict of `opcode → [block_id, ...]` for top-level hats. `_is_clone`. |

### Variable & ListVar

```python
@dataclass
class Variable:
    name: str
    value: Any = 0
    is_cloud: bool = False

@dataclass
class ListVar:
    name: str
    contents: list = field(default_factory=list)
```

---

## 2. Scheduler & Execution Model

### Main Loop (Renderer + Runtime)

```
Render.run() @ 60 fps:
  _handle_events() → pygame events → key/click hats
  _sync_keyboard() → copies key state to runtime
  _sync_mouse()   → copies mouse position to runtime
  _update():
    clear expired say bubbles
    handle pen stamps/clear
    runtime.step()   ← advances simulation one tick
  _draw():
    draw stage backdrop
    for each sprite (sorted by layer_order):
      _draw_sprite(sprite)
      _draw_bubble(sprite)  ← speech/think bubble
    draw pen layer
    draw info overlay
```

### `Runtime.step()` — One Frame

Three phases per frame:

1. **Wake phase**: pop from `_wait_queue` (min-heap by wake time) all threads whose timer expired → `WAITING → RUNNING`.
2. **Step phase**: iterate all runnable threads, calling `_step_thread(thread)` once per thread. Threads staying `RUNNING` are collected.
3. **Tick**: `clock.tick()` advances the virtual frame counter.

### `_step_thread(thread)` — One Instruction

1. Peek top frame. None → `DONE`.
2. Look up block by ID. Missing → pop frame.
3. Look up handler. Missing → advance to next block.
4. If handler not started (`frame.gen is None`):
   - Call `handler(runtime, target, block)`.
   - Returns `None` / non-generator → instant block → `_advance_to_next`.
   - Returns `GeneratorType` → store on `frame.gen`.
5. `next(frame.gen)` — resume generator:
   - **`StopIteration`** → `_advance_to_next`.
   - **`Report(value)`** → pop frame, deliver to parent's `saved['_result']`.
   - **`Wait(secs)`** → `_schedule_wake(thread, secs)`.
   - **`YieldPass()`** → reschedule next tick.
   - **`_`** → `RuntimeError` (exhaustive check).

### Block Chaining

`_advance_to_next(thread)`:
- If `block.next` exists → replace `frame.block_id` with next, reset `frame.gen`.
- Else → `pop_frame()`. Empty stack → `DONE`.

This implements Scratch's linked-list chains: sequential blocks occupy one stack level, replacing each other.

### Substack Execution

`execute_substack(target, block_id, yield_between=True)` is a generator stepped through by control blocks:

1. Walk `block.next` links.
2. For each block, call handler:
   - Instant handler (returns `None`) → advance to next block, yield `YIELD` between blocks (if `yield_between=True`).
   - Generator handler → iterate via `while True: val = next(gen)` and re-yield every value upward.
3. Control block retains control between iterations for its own YIELD/condition check.

Used by: `control_repeat`, `control_forever`, `control_if`, `control_if_else`, `control_repeat_until`, `control_while`, `control_for_each`, `control_all_at_once`, and `procedures_call`.

---

## 3. Yield Protocol

Handlers signal control flow by yielding one of three dataclasses:

| Signal | Meaning |
|--------|---------|
| `YieldPass()` | Yield control; thread stays runnable, rescheduled next tick. |
| `Wait(seconds)` | Pause thread for `seconds`; moved to waiting queue (heap by wake time). |
| `Report(value)` | Reporter returning a value to the parent frame. |

The scheduler dispatches via `match`:

```python
match yielded:
    case Report(value):   → store in parent frame, pop
    case Wait(seconds):   → schedule wake
    case YieldPass():     → reschedule
    case _:               → RuntimeError
```

---

## 4. Hat & Event System

### Hat Index

`Runtime._hat_index: dict[str, list[tuple[Target, str]]]` — maps opcode strings to `(target, block_id)` pairs. Populated by `_index_target_hats(target)` whenever a target is added.

### Hat Activation

| Activation method | Trigger | Implementation |
|---|---|---|
| `start_hat(opcode)` | Green flag, broadcast | Creates Thread for each `(target, bid)` in hat index. |
| `start_hat_for_opcode(opcode, target)` | Clone init | Scoped to one target. |
| `start_key_hat(key_name)` | Keyboard press | Filters `event_whenkeypressed` by `KEY_OPTION` field. `'any'` wildcard matches all keys. |
| `start_click_hat(x, y)` | Mouse click | Hit-tests sprites in reverse layer order (bounding circle). Falls through to stage. |

### Edge-Activated Hats

Hats like `event_whentouchingobject` and `event_whengreaterthan` only fire on **false → true** transition. The runtime stores previous values in `_edge_hat_values` and checks `_check_edge_hat(opcode, target, block, current_value)`.

### Broadcast

`broadcast(message)` matches `BROADCAST_OPTION` against the message by direct string comparison first, then by iterating `target.broadcasts` (ID → name matching).

### Restart Existing Threads

Most hats have `restartExistingThreads: true` — they stop any existing thread for that hat+target combo before starting a new one. Keypress and edge-activated hats have `restartExistingThreads: false`.

---

## 5. Input Resolution & Type System

### Resolution Pipeline

```
val(name)       num(name)       truthy(name)
    │               │               │
    └── _input_raw(block, name) ─────┘
              │
              ↓  strips Input wrapper → raw value
    resolve_input(target, raw_value)
              │
              ├── str in target.blocks → evaluate(reporter)
              ├── [type_code, ref]     → see Primitive Types below
              ├── [block_id, literal]  → return literal (shadow pair)
              └── else                → return as-is
```

### Inlined Primitive Type Codes (SB3 Compression)

When SB3 serializes a primitive shadow block inline, the value becomes `[type_code, ...]`:

| Code | Opcode | Meaning |
|------|--------|---------|
| 4 | `math_number` | Numeric literal |
| 5 | `math_positive_number` | Positive number literal |
| 6 | `math_whole_number` | Whole number literal |
| 7 | `math_integer` | Integer literal |
| 8 | `math_angle` | Angle literal |
| 9 | `colour_picker` | Color value (hex string or packed int) |
| 10 | `text` | String literal |
| 11 | `event_broadcast_menu` | Broadcast message name |
| 12 | `data_variable` | **Variable reference** — look up by id/name, return value |
| 13 | `data_listcontents` | **List reference** — look up by id/name, return contents |

### Type Casting (from scratch-vm Cast.js)

| Function | Behavior |
|----------|----------|
| `toNumber(v)` | `Number(v)`; NaN → 0. Never returns NaN. |
| `toString(v)` | `String(v)`. |
| `toBoolean(v)` | Falsy: `''`, `'0'`, `'false'` (case-insensitive), `0`, `NaN`, `null`, `undefined`. |
| `compare(v1, v2)` | Three-way. If both whitespace/null → NaN (string compare). If either NaN → case-insensitive string compare. Else numeric. |
| `toListIndex(v, len)` | Converts `'all'`, `'last'`, `'random'`, `'any'` string values to special constants or 1-based indices. |

---

## 6. Clone System

```python
clone_target(target_name):
  1. Find source sprite by name (reject stage).
  2. copy.deepcopy(src) — full deep copy.
  3. Mark _is_clone = True, rename to "{name}_clone".
  4. Append to targets list (insert after original for z-order).
  5. Re-index hat blocks.
  6. Start hats: event_whenflagclicked, event_whenthisspriteclicked, control_start_as_clone.

remove_clone(clone):
  1. Verify _is_clone.
  2. Remove from _clones, targets.
  3. Kill all threads on this target.
```

---

## 7. Procedure / Custom Block System

### Call Flow

```
procedures_call block:
  1. Get call block's mutation → proccode.
  2. Scan target blocks for procedures_definition with matching proccode.
  3. Parse argumentids / argumentnames / argumentdefaults from definition mutation.
  4. For each arg: if present in block.inputs, resolve via val(); else use default, else ''.
  5. Store resolved values in frame.saved[arg_name].
  6. yield from execute_substack(target, definition.next)

argument_reporter_string_number / _boolean:
  1. Read arg name from fields.VALUE.
  2. Look up frame.saved[arg_name] on the current frame.
  3. If found → yield Report(value); else yield Report(0).
```

### SB3 Deserialization

- Mutation is stored as a dict in `block.mutation` with `proccode`, `argumentids`, `argumentnames`, `argumentdefaults`, `warp`.
- `procedures_prototype` is a non-runtime structural block whose children (`argument_reporter_*`) are deleted during deserialization and recreated by Blockly's `domToMutation`.

---

## 8. SB3 Serialization Format

Source: `scratch-vm/src/serialization/sb3.js`

### Input Format — Shadow/Block Relationship

Each block input is serialized as `[code, blockId, ?shadowId]`:

| Code | Constant | Meaning | Array |
|------|----------|---------|-------|
| `1` | `INPUT_SAME_BLOCK_SHADOW` | block === shadow (unobscured shadow, most common) | `[1, idOrPrimitive]` |
| `2` | `INPUT_BLOCK_NO_SHADOW` | block present, shadow is null | `[2, blockId]` |
| `3` | `INPUT_DIFF_BLOCK_SHADOW` | block and shadow are different (obscured shadow) | `[3, blockId, shadowId]` |

### Primitive Type Codes (Inlined Shadows)

Primitive shadow blocks (math_number, text, variable getters, etc.) are serialized inline as short arrays instead of full block objects:

| Code | Constant | Block Opcode | Field Name | Format |
|------|----------|-------------|------------|--------|
| `4` | `MATH_NUM_PRIMITIVE` | `math_number` | `NUM` | `[4, value]` |
| `5` | `POSITIVE_NUM_PRIMITIVE` | `math_positive_number` | `NUM` | `[5, value]` |
| `6` | `WHOLE_NUM_PRIMITIVE` | `math_whole_number` | `NUM` | `[6, value]` |
| `7` | `INTEGER_NUM_PRIMITIVE` | `math_integer` | `NUM` | `[7, value]` |
| `8` | `ANGLE_NUM_PRIMITIVE` | `math_angle` | `NUM` | `[8, value]` |
| `9` | `COLOR_PICKER_PRIMITIVE` | `colour_picker` | `COLOUR` | `[9, value]` |
| `10` | `TEXT_PRIMITIVE` | `text` | `TEXT` | `[10, value]` |
| `11` | `BROADCAST_PRIMITIVE` | `event_broadcast_menu` | `BROADCAST_OPTION` | `[11, value, id]` |
| `12` | `VAR_PRIMITIVE` | `data_variable` | `VARIABLE` | `[12, value, id, ?x, ?y]` |
| `13` | `LIST_PRIMITIVE` | `data_listcontents` | `LIST` | `[13, value, id, ?x, ?y]` |

Notes:
- For codes 11–13, the third element is the variable/list/broadcast **id**.
- For codes 12–13, if followed by `x, y` the variable/list is a top-level monitor.
- For codes 4–10, the value is the literal (string, number).
- Codes 4–13 intentionally overlap with codes 1–3 (disjoint contexts).

### Variable, List, and Broadcast Encoding

**Scalar variables** (`target.variables`):
```json
{
  "varId": ["variable name", value],
  "cloudVarId": ["☁ score", 100, true]
}
```
Third element for cloud variables (stage only) is `true`.

**Lists** (`target.lists`):
```json
{
  "listId": ["list name", ["item1", "item2"]]
}
```

**Broadcasts** (`target.broadcasts`):
```json
{
  "broadcastId": "message1"
}
```

### Field Encoding

```json
// Simple field
{"fieldName": ["value"]}

// Field with id (variable, list, broadcast dropdowns)
{"VARIABLE": ["my var", "varId123"]}
{"LIST": ["my list", "listId456"]}
{"BROADCAST_OPTION": ["message1", "broadcastId789"]}
```

The `variableType` is NOT serialized — it's recovered by field name convention:
- `BROADCAST_OPTION` → `broadcast_msg`
- `VARIABLE` → `''` (scalar)
- `LIST` → `'list'`

### Block Serialization

A full block (non-primitive) serializes as:
```json
{
  "opcode": "motion_movesteps",
  "next": "nextBlockId",
  "parent": "parentBlockId",
  "inputs": {
    "STEPS": [1, [4, "10"]]
  },
  "fields": {},
  "shadow": false,
  "topLevel": true,
  "x": 100,
  "y": 200,
  "mutation": { ... }
}
```

### Compression Pipeline

1. **Serialize** each block. Primitives become compact arrays `[typeCode, value, ...]`.
2. **Compress** (`compressInputTree`): replace block IDs in input arrays with inline primitive arrays. Delete the now-orphaned primitive block entries.
3. **Cleanup**: remove remaining top-level primitive arrays (except VAR/LIST, which can be legitimately top-level).

Deserialization reverses this: `deserializeInputDesc` converts primitive arrays back to full block objects with fresh `uid()`s.

### Shadow Repair (Deserialization)

After deserialization, a third pass repairs missing/broken shadows:
- Detects `shadowIsBroken` (shadow ID points to nonexistent block) and `shadowIsMissing` (shadow is null when it shouldn't be).
- Finds a peer block (same opcode + input) with a working shadow via `findPeerShadow`.
- Rebuilds the shadow using `buildShadowFields(shadowOpcode, template)`.

### Procedures Prototype Special Case

During deserialization, `procedures_prototype` blocks have their input children (`argument_reporter_*`) **deleted** from the blocks map. Blockly's `domToMutation` recreates them from the mutation data.

### Mutation Format

```json
{
  "tagName": "mutation",
  "proccode": "myBlock %n %s",
  "argumentids": "[\"uuid1\",\"uuid2\"]",
  "argumentnames": "[\"x\",\"y\"]",
  "argumentdefaults": "[\"0\",\"\"]",
  "warp": "false"
}
```
Mutations are opaque to the serializer — passed through verbatim.

### Examples

**Inline math_number shadow:**
```json
{"STEPS": [1, [4, "10"]]}
```

**Obscured shadow (reporter plugged in with shadow fallback):**
```json
{"VALUE": [3, "reporterBlockId", [7, "0"]]}
```

**Variable getter inline (no x/y, not top-level):**
```json
{"VARIABLE": [1, [12, "my var", "actualVarId"]]}
```

**Top-level variable monitor:**
```json
// In blocks dict (not inside an input):
{"varBlockId": [12, "my var", "actualVarId", 150, 50]}
```

**Broadcast inline:**
```json
{"BROADCAST_INPUT": [1, [11, "message1", "broadcastId"]]}
```
