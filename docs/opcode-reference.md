# Scratch VM Opcode Reference

> Extracted from [scratch-editor/scratch-vm](https://github.com/scratchfoundation/scratch-vm) (`packages/scratch-vm/src/blocks/`).

## Yielding & Scheduling

### Yield signals (JavaScript implementation)

The sequencer (sequencer.js) uses thread status codes — not yielded values — for control flow. A primitive returns `void`/`Promise`, and the sequencer inspects `thread.status` afterwards.

| Signal | Meaning | Set by |
|--------|---------|--------|
| `STATUS_RUNNING` (0) | Default; thread is stepped normally | — |
| `STATUS_PROMISE_WAIT` (1) | Yielding until a Promise resolves | `handlePromise()` when primitive returns a Promise |
| `STATUS_YIELD` (2) | Yield this frame; continue next frame (or within warp) | `util.yield()` |
| `STATUS_YIELD_TICK` (3) | Yield until next tick (frame) | `util.yieldTick()` |
| `STATUS_DONE` (4) | Thread finished | Sequencer when stack empties |

### Sequencer stepping (sequencer.js)

**`stepThreads()`** — outer loop, called each frame from `Runtime._step()`:
- Runs a `while`-loop over ALL threads as long as:
  - Threads remain with active status
  - Time elapsed < `WORK_TIME` (75% of `currentStepTime`, ≈12.5ms at 60fps)
  - Either turbo mode OR no redraw was requested
- Each "tick" iterates every thread once.
- `STATUS_YIELD_TICK` is cleared at start of first tick.
- After each full tick, completed threads (empty stack or `STATUS_DONE`) are filtered out.

**`stepThread(thread)`** — inner per-thread loop:
- Loops while `thread.peekStack()` is non-null.
- Calls `execute(this, thread)` to run current block's primitive.
- If `STATUS_YIELD`: reset to RUNNING; if warp mode + timer < 500ms, continue; else return.
- If `STATUS_PROMISE_WAIT`: return (waiting for async).
- If `STATUS_YIELD_TICK`: return.
- If stack top unchanged, call `thread.goToNextBlock()`.
- When stack empties → `STATUS_DONE`.

### Wait timing

- `control_wait` multiplies by 1000 (seconds → ms) and calls `util.startStackTimer(duration)`.
- Warp mode (`WARP_TIME = 500ms`) lets loops inside procedure definitions run without yielding between iterations.
- Redraw is requested before yield so the renderer knows to update.

### Substack execution (branches)

- `util.startBranch(branchNum, loopFlag)` pushes a new stack frame pointing to the substack input's first block.
- `branchNum = 1` or `2` (for C-shaped blocks like `if-else`).
- `loopFlag = true` marks the frame as a loop (frame reports `isLoop = true`), which makes the sequencer yield between iterations.
- `util.startProcedure(proccode, paramValuesMap)` pushes procedure body onto stack with param values saved for argument reporters.

### Edge-activated hats

- Edge-activated hats (like `event_whentouchingobject`, `event_whengreaterthan`) only fire when transitioning from **false → true**.
- The hat stores `edgeActivatedHatValues` in the runtime, keyed by opcode + target.
- Each step, the runtime calls `updateEdgeHats()` which evaluates the hat's primitive and compares with the stored value.
- If previous was falsy and current is truthy → start threads.
- Edge hats have `restartExistingThreads: false` (don't restart already-running threads).

### Procedure argument passing

- `util.getParam(paramName)` looks up the current procedure call's parameter by name from `thread.params`.
- `procedures_call` handler does:
  1. Look up procedure definition by proccode.
  2. Parse `argumentids` / `argumentnames` / `argumentdefaults` from the definition's mutation.
  3. Build `params = {}`. For each argument: if call block has it in `args`, use `args[argId]`; else use default from mutation; else `''`.
  4. Call `util.startProcedure(proccode, params)` which pushes the definition's body onto the stack with `thread.params = params`.
- `argument_reporter_string_number` / `argument_reporter_boolean` call `util.getParam(args.VALUE)`. If not found, return `0`.

---

## Cast Semantics

All from `Cast.js` (`src/util/cast.js`).

### `Cast.toNumber(value)` — never returns NaN

| Input | Result |
|-------|--------|
| `NaN` | `0` |
| `undefined`, `null` | `0` |
| `true` | `1` |
| `false` | `0` |
| `""` | `0` |
| `"hello"` | `0` |
| `"Infinity"` | `Infinity` |
| `[]` | `0` |
| `[3]` | `3` |
| `[1, 2]` | `0` |

### `Cast.toString(value)` — plain `String(value)`

`null` → `"null"`, `undefined` → `"undefined"`, arrays → comma-joined, etc.

### `Cast.toBoolean(value)` — Scratch boolean

| Input | Result |
|-------|--------|
| `"0"` | `false` |
| `"false"` (case-insensitive) | `false` |
| `""` | `false` |
| `0` | `false` |
| `NaN`, `null`, `undefined` | `false` |
| `" "`, `"false "`, `"1"` | `true` |
| non-empty objects/arrays | `true` |

### `Cast.compare(v1, v2)` — three-way comparison

1. If both are whitespace strings (or `null`) → treat both as NaN.
2. Convert both to Number. If **either is NaN** → case-insensitive string compare (`.toLowerCase().localeCompare()`).
3. If both are `±Infinity` → `0`.
4. Otherwise → `n1 - n2` (numeric).

Key behavior: whitespace strings that `Number()` to 0 are treated as NaN, forcing string comparison. So `Cast.compare(0, "")` > 0 (numeric 0 stays, `""` whitespace → NaN → string compare: `"0" > ""`).

### `Cast.toListIndex(value, length, acceptAll?)`

Converts a Scratch list index argument:
- If typeof is not `'number'`:
  - `"all"` → `LIST_ALL` (if acceptAll) else `LIST_INVALID`
  - `"last"` → `length` (if > 0) else `LIST_INVALID`
  - `"random"` / `"any"` → `1 + floor(random * length)` (if > 0) else `LIST_INVALID`
- Otherwise: `floor(toNumber(value))`. If < 1 or > length → `LIST_INVALID`.

Constants: `LIST_INVALID = 'INVALID'`, `LIST_ALL = 'ALL'`.

---

## Motion

### `motion_movesteps`
- **BlockType**: command
- **Inputs**: `[STEPS: number]` (shadow: `math_number`, default 10)
- **Semantics**: Move sprite `STEPS` pixels in current direction. `rad = (90 - direction) * π/180`. `dx = steps × cos(rad)`, `dy = steps × sin(rad)`. Added to current position via `setXY`.

### `motion_turnright`
- **Inputs**: `[DEGREES: number]` (shadow: `math_number`, default 15)
- **Semantics**: `direction += DEGREES`

### `motion_turnleft`
- **Inputs**: `[DEGREES: number]` (shadow: `math_number`, default 15)
- **Semantics**: `direction -= DEGREES`

### `motion_pointindirection`
- **Inputs**: `[DIRECTION: angle]` (shadow: `math_angle`, default 90)
- **Semantics**: `direction = DIRECTION`

### `motion_pointtowards`
- **Inputs**: `[TOWARDS: menu]` (menu block: `motion_pointtowards_menu`)
- **Menu options**: `_mouse_` + all sprite names.
- **Semantics**: `_mouse_` → ioQuery for mouse coords. `_random_` → random direction. Named sprite → `atan2(dy, dx)` with 90° offset.

### `motion_goto`
- **Inputs**: `[TO: menu]` (menu block: `motion_goto_menu`)
- **Menu options**: `_random_`, `_mouse_` + all sprite names.
- **Semantics**: Calls `getTargetXY(TO)`. `_random_` → random within stage bounds. `_mouse_` → ioQuery. Named → getSpriteTargetByName.

### `motion_gotoxy`
- **Inputs**: `[X: number, Y: number]` (shadow: `math_number`, default 0)
- **Semantics**: `setXY(X, Y)`

### `motion_glidesecstoxy`
- **Inputs**: `[SECS: number, X: number, Y: number]` (shadows: `math_number`, defaults 1/0/0)
- **Semantics**: Glides from current position over SECS seconds using stackFrame state machine. First call saves start/end/duration and starts timer. Subsequent calls compute elapsed fraction and interpolate. If duration ≤0, teleports immediately. Yields while gliding.

### `motion_glideto`
- **Inputs**: `[SECS: number, TO: menu]` (menu block: `motion_glideto_menu`)
- **Semantics**: Resolves TO via `getTargetXY`, delegates to `glide({SECS, X, Y})`.

### `motion_ifonedgebounce`
- **BlockType**: command, no inputs.
- **Semantics**: Computes distance to all 4 stage edges using sprite bounds. If touching edge (minDist = 0), adjusts direction away from nearest edge (minimum 0.2 velocity component). Then calls `keepInFence()` to stay within stage.

### `motion_setrotationstyle`
- **Fields**: `[STYLE: dropdown]` — options: `[["all around", "all around"], ["left-right", "left-right"], ["don't rotate", "don't rotate"]]`

### `motion_changexby` / `motion_setx` / `motion_changeyby` / `motion_sety`
- **Inputs**: `[DX/DY/X/Y: number]` (shadow: `math_number`, default 10 for change, 0 for set)
- **Semantics**: Add or set x/y position.

### `motion_xposition` / `motion_yposition`
- **BlockType**: reporter, no inputs.
- **Monitored**: yes, sprite-specific (`${targetId}_xposition`).
- **Semantics**: Returns `target.x/y` via `limitPrecision` (rounds to integer when delta < 1e-9).

### `motion_direction`
- **BlockType**: reporter, no inputs.
- **Monitored**: yes, sprite-specific.
- **Semantics**: Returns `target.direction`.

### Legacy no-ops
- `motion_scroll_right`, `motion_scroll_up`, `motion_align_scene`, `motion_xscroll`, `motion_yscroll`

---

## Looks

### `looks_say`
- **BlockType**: command
- **Inputs**: `[MESSAGE: string]`
- **Semantics**: Emits `SAY` event + sets `target.sayText`. Bubble persists until replaced or cleared. Has a `330` char limit.

### `looks_sayforsecs`
- **Inputs**: `[MESSAGE: string, SECS: number]`
- **Semantics**: Calls `say()`, sets timeout (`SECS × 1000` ms). Uses `usageId` to check if bubble unchanged; if so, clears bubble. Returns Promise (yields thread).

### `looks_think` / `looks_thinkforsecs`
- Same as `say`/`sayforsecs` but emits `THINK` event.

### `looks_show` / `looks_hide`
- **Semantics**: `target.setVisible(true/false)`. Sprite-only (not in Stage toolbox).

### `looks_switchcostumeto`
- **BlockType**: command
- **Inputs**: `[COSTUME: costume]` (menu: `looks_costume`)
- **Semantics**: Calls `_setCostume`. Numbers → 1-indexed. Strings → name match, then `'next costume'`/`'previous costume'`, then numeric parse. Pure whitespace not cast to number.

### `looks_switchbackdropto`
- **Inputs**: `[BACKDROP: backdrop]` (menu: `looks_backdrops`)
- **Semantics**: Calls `_setBackdrop` on stage. Recognizes `'next backdrop'`, `'previous backdrop'`, `'random backdrop'`. `'random backdrop'` uses exclusive random (never picks current). Returns threads started by `event_whenbackdropswitchesto`.

### `looks_switchbackdroptoandwait`
- Same as `looks_switchbackdropto` but waits for all started hat threads to finish.

### `looks_nextcostume` / `looks_nextbackdrop`
- **Semantics**: Calls `_setCostume` / `_setBackdrop` with `current + 1` (0-indexed → wrapped).

### `looks_changeeffectby` / `looks_seteffectto`
- **Inputs**: `[CHANGE/VALUE: number]` (shadow: `math_number`, default 25/0)
- **Fields**: `[EFFECT: dropdown]` — `color`, `fisheye`, `whirl`, `pixelate`, `mosaic`, `brightness`, `ghost`
- **Clamp limits**: ghost: 0–100, brightness: -100–100. Others unbounded.

### `looks_cleargraphiceffects`
- **Semantics**: `target.clearEffects()`. Available for both sprites and stage.

### `looks_changesizeby` / `looks_setsizeto`
- **Inputs**: `[CHANGE/SIZE: number]` (shadow: `math_number`, defaults: 10/100)
- **Semantics**: `target.setSize(size)`. Sprite-only.

### `looks_gotofrontback`
- **Fields**: `[FRONT_BACK: dropdown]` — `front`, `back`. No-op if `target.isStage`.

### `looks_goforwardbackwardlayers`
- **Inputs**: `[NUM: integer]` (shadow: `math_integer`, default 1)
- **Fields**: `[FORWARD_BACKWARD: dropdown]` — `forward`, `backward`. No-op if stage.

### `looks_size`
- **BlockType**: reporter, no inputs.
- **Returns**: `Math.round(util.target.size)`. Monitored (sprite-specific).

### `looks_costumenumbername`
- **BlockType**: reporter, no inputs.
- **Fields**: `[NUMBER_NAME: dropdown]` — options: `"number"`, `"name"`
- **Returns**: If `"number"` → `costumeIndex + 1`. If `"name"` → `currentCostumeName`.

### `looks_backdropnumbername`
- Same as `costumenumbername` but operates on stage target.

### `looks_costume`
- **BlockType**: reporter. **Menu block** for `looks_switchcostumeto`.
- **Fields**: `[COSTUME: dropdown]` — lists costume names.
- **Returns**: The selected costume name from the `COSTUME` field value.

### Legacy no-ops: `looks_hideallsprites`, `looks_changestretchby`, `looks_setstretchto`

---

## Sound

### `sound_play`
- **BlockType**: command
- **Inputs**: `[SOUND_MENU: input_value]` (shadow: `sound_sounds_menu`)
- **Semantics**: Starts playing the selected sound. Fire-and-forget (no promise). Immediately continues to next block. Sound resolved by name first (exact match), then by 1-indexed numeric index via `wrapClamp`. Silently no-ops if no matching sound.

### `sound_playuntildone`
- **Inputs**: `[SOUND_MENU: input_value]` (shadow: `sound_sounds_menu`)
- **Semantics**: Plays selected sound and waits until it finishes. Registers `soundId` in `waitingSounds` for the target so `STOP_FOR_TARGET` can cancel it. Returns the promise from `soundBank.playSound()`.

### `sound_stopallsounds`
- **BlockType**: command, no inputs.
- **Semantics**: Stops all sounds on all targets via `soundBank.stopAllSounds()`. Clears all `waitingSounds` sets. Also registered on `PROJECT_STOP_ALL` event.

### `sound_seteffectto`
- **Inputs**: `[VALUE: number]` (shadow: `math_number`, default 100)
- **Fields**: `[EFFECT: dropdown]` — options: `"pitch"`, `"pan"`
- **Semantics**: Sets `soundState.effects[effect] = value`. Clamps pitch to -360..360, pan to -100..100. Syncs to soundBank. Returns `Promise.resolve()` (yields until next tick). Unknown effect names silently ignored.

### `sound_changeeffectby`
- **Inputs**: `[VALUE: number]` (shadow: `math_number`, default 10)
- **Fields**: `[EFFECT: dropdown]` — `"pitch"`, `"pan"`
- **Semantics**: Adds value to `soundState.effects[effect]`, clamps, syncs. Returns `Promise.resolve()`.

### `sound_cleareffects`
- **BlockType**: command, no inputs.
- **Semantics**: Resets all sound state effects to 0. Syncs to soundBank. Also registered on `PROJECT_STOP_ALL` and `PROJECT_START` events.

### `sound_setvolumeto`
- **Inputs**: `[VOLUME: number]` (shadow: `math_number`, default 100)
- **Semantics**: Sets `target.volume = clamp(value, 0, 100)`. Syncs effects. Returns `Promise.resolve()`.

### `sound_changevolumeby`
- **Inputs**: `[VOLUME: number]` (shadow: `math_number`, default -10)
- **Semantics**: Sets `target.volume = clamp(target.volume + value, 0, 100)`. Returns `Promise.resolve()`.

### `sound_volume`
- **BlockType**: reporter, no inputs.
- **Monitored**: yes, sprite-specific (`${targetId}_volume`).
- **Returns**: `util.target.volume` (number 0-100).

### Menu blocks
- `sound_sounds_menu` — field `[SOUND_MENU: dropdown]`, dynamic from sprite's sound names plus `"record..."`.
- `sound_beats_menu` — field `[BEATS: dropdown]`, passthrough reporter.
- `sound_effects_menu` — field `[EFFECT: dropdown]`, passthrough reporter for pitch/pan.

### Constants
- `EFFECT_RANGE`: pitch -360..360, pan -100..100.
- `DEFAULT_SOUND_STATE`: `{effects: {pitch: 0, pan: 0}}`.

---

## Events

### Hat blocks — all `restartExistingThreads` flags:

| Opcode | restartExisting | edgeActivated |
|--------|----------------|---------------|
| `event_whenflagclicked` | `true` | no |
| `event_whenkeypressed` | `false` | no |
| `event_whenthisspriteclicked` | `true` | no |
| `event_whenstageclicked` | `true` | no |
| `event_whenbroadcastreceived` | `true` | no |
| `event_whentouchingobject` | `false` | **yes** |
| `event_whengreaterthan` | `false` | **yes** |
| `event_whenbackdropswitchesto` | `true` | no |

### `event_whenkeypressed`
- **Fields**: `[KEY_OPTION: dropdown]`
- **Semantics**: Fires on KEY_PRESSED event. Starts hats for both exact key match AND `"any"` wildcard. Also triggered by mouseWheel.

### `event_whenthisspriteclicked`
- Remapped to/from `event_whenstageclicked` during project load depending on target type (sprite vs stage).

### `event_whentouchingobject`
- **Inputs**: `[TOUCHINGOBJECTMENU: menu]` — `_mouse_`, `_edge_`, sprite names.
- **Edge-activated**: fires when sprite **starts** touching the object.

### `event_whengreaterthan`
- **Inputs**: `[VALUE: number]` (shadow: `math_number`, default 10)
- **Fields**: `[WHENGREATERTHANMENU: dropdown]` — `"timer"`, `"loudness"`
- **Edge-activated**: fires when sensor > VALUE transition occurs.

### `event_whenbackdropswitchesto`
- **Fields**: `[BACKDROP: dropdown]` — dynamic from stage costume names, plus `"next backdrop"`, `"previous backdrop"`, `"random backdrop"`.

### `event_broadcast`
- **Inputs**: `[BROADCAST_INPUT: input_value]` with shadow menu `event_broadcast_menu`
- **Semantics**: Looks up broadcast msg by id/name, calls `util.startHats('event_whenbroadcastreceived', {BROADCAST_OPTION: ...})`. Fire-and-forget.

### `event_broadcastandwait`
- Same as `event_broadcast` but waits for all triggered scripts. Uses `stackFrame.startedThreads` and yields until threads complete.

---

## Control

### `control_repeat`
- **Inputs**: `[TIMES: math_whole_number, SUBSTACK: substack]`
- **Semantics**: `Math.round(TIMES)`. Uses `util.stackFrame.loopCounter`. Executes at most once per frame via yield counter. Decrements counter, starts branch when ≥ 0.

### `control_repeat_until`
- **Inputs**: `[CONDITION: boolean, SUBSTACK: substack]`
- **Semantics**: Runs body while `!condition` → `util.startBranch(1, true)`.

### `control_while`
- **Inputs**: `[CONDITION: boolean, SUBSTACK: substack]`
- **Semantics**: Runs body while `condition` → `util.startBranch(1, true)`.

### `control_for_each`
- **Inputs**: `[VALUE: text, SUBSTACK: substack]`
- **Fields**: `[VARIABLE: variable_picker]`
- **Semantics**: Iterates `index` from 0 to `< Number(args.VALUE)`. Sets variable.value = index each iteration. Variable lookup via `util.target.lookupOrCreateVariable(VARIABLE.id, VARIABLE.name)`.

### `control_forever`
- **Inputs**: `[SUBSTACK: substack]`
- **Semantics**: Always starts branch 1 with `looping = true`.

### `control_wait`
- **Inputs**: `[DURATION: math_positive_number]`
- **Semantics**: `Math.max(0, 1000 × Cast.toNumber(DURATION))` → ms. Uses `util.startStackTimer(duration)` + `util.stackTimerFinished()`. Calls `runtime.requestRedraw()` before yield.

### `control_wait_until`
- **Inputs**: `[CONDITION: boolean]`
- **Semantics**: If condition is false, calls `util.yield()` to pause. Re-enters on next tick. No branch start.

### `control_if`
- **Inputs**: `[CONDITION: boolean, SUBSTACK: substack]`
- **Semantics**: Starts branch 1 (non-looping) when condition truthy.

### `control_if_else`
- **Inputs**: `[CONDITION: boolean, SUBSTACK: substack, SUBSTACK2: substack]`
- **Semantics**: Condition truthy → branch 1 (non-looping), else branch 2 (non-looping).

### `control_stop`
- **Fields**: `[STOP_OPTION: dropdown]` — options: `"all"`, `"other scripts in sprite"`, `"other scripts in stage"`, `"this script"`.
- **Semantics**: `"all"` → `util.stopAll()`. `"other scripts in sprite/stage"` → `util.stopOtherTargetThreads()`. `"this script"` → `util.stopThisScript()`.

### `control_create_clone_of`
- **Inputs**: `[CLONE_OPTION: menu]` — `_myself_` + all sprite names.
- **Semantics**: `_myself_` → clone current target. Else lookup by name. Creates clone, adds to runtime, sets behind original. Silent no-op if target not found.

### `control_delete_this_clone`
- **Semantics**: If `util.target.isOriginal` → return. Else `runtime.disposeTarget` + `runtime.stopForTarget`.

### `control_start_as_clone`
- Hat block (no restartExistingThreads), `edgeActivated`: no.

### `control_get_counter` / `control_incr_counter` / `control_clear_counter`
- Internal counter block. `_counter = 0` initially. `incrCounter`: `_counter++`. `clearCounter`: `_counter = 0`. `getCounter`: returns `_counter`.

### `control_all_at_once`
- **Inputs**: `[SUBSTACK: substack]`
- **Semantics**: Scratch 2.0 compat. Runs contained script non-looping (like an always-true `if`).

---

## Operators

### Arithmetic
| Opcode | Inputs | Behavior |
|--------|--------|----------|
| `operator_add` | `NUM1, NUM2` | `toNumber(NUM1) + toNumber(NUM2)` |
| `operator_subtract` | `NUM1, NUM2` | `toNumber(NUM1) - toNumber(NUM2)` |
| `operator_multiply` | `NUM1, NUM2` | `toNumber(NUM1) × toNumber(NUM2)` |
| `operator_divide` | `NUM1, NUM2` | `toNumber(NUM1) ÷ toNumber(NUM2)`; division by zero → `Infinity` |
| `operator_mod` | `NUM1, NUM2` | Scratch floored-mod: always non-negative remainder |
| `operator_round` | `NUM` | `Math.round(toNumber(NUM))` |
| `operator_random` | `FROM, TO` | If both ints: inclusive integer in `[low, high]`. Else: float in `[low, high)`. Low/high auto-ordered. If equal → low. |

### Comparison
| Opcode | Inputs | Behavior |
|--------|--------|----------|
| `operator_lt` | `OPERAND1, OPERAND2` | `Cast.compare(v1, v2) < 0` |
| `operator_equals` | `OPERAND1, OPERAND2` | `Cast.compare(v1, v2) === 0` |
| `operator_gt` | `OPERAND1, OPERAND2` | `Cast.compare(v1, v2) > 0` |
| `operator_and` | `OPERAND1, OPERAND2` | `toBoolean(v1) && toBoolean(v2)` |
| `operator_or` | `OPERAND1, OPERAND2` | `toBoolean(v1) \|\| toBoolean(v2)` |
| `operator_not` | `OPERAND` | `!toBoolean(v)` |

### String
| Opcode | Inputs | Behavior |
|--------|--------|----------|
| `operator_join` | `STRING1, STRING2` | `toString(v1) + toString(v2)` |
| `operator_letter_of` | `LETTER, STRING` | `str.charAt(index - 1)`; `''` if out of range |
| `operator_length` | `STRING` | `toString(v).length` |
| `operator_contains` | `STRING1, STRING2` | Case-insensitive: `s1.toLowerCase().includes(s2.toLowerCase())` |

### Math
| Opcode | Fields | Behavior |
|--------|--------|----------|
| `operator_mathop` | `[OPERATOR: dropdown]` — `abs`, `floor`, `ceiling`, `sqrt`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `ln`, `log`, `e ^`, `10 ^` | Trig in degrees. `toFixed(10)` for sin/cos to avoid float artifacts. Unknown → `0`. |

---

## Data — Variables

Variable and list block opcodes. Variables are stored on targets keyed by ID.

### `data_variable`
- **BlockType**: reporter
- **Arguments**: `[VARIABLE: field_dropdown]` — name+id selector.
- **Returns**: `variable.value`. If variable doesn't exist, `lookupOrCreateVariable` creates it on the target with default value `0`.

### `data_setvariableto`
- **BlockType**: command
- **Arguments**: `[VARIABLE: field_dropdown, VALUE: input_value]`
- **Semantics**: `variable.value = VALUE`. If cloud variable (`variable.isCloud`), sends cloud update.

### `data_changevariableby`
- **Arguments**: `[VARIABLE: field_dropdown, VALUE: input_value]`
- **Semantics**: `variable.value = toNumber(current) + toNumber(delta)`.

### `data_showvariable` / `data_hidevariable`
- Semantics: `changeMonitorVisibility(args.VARIABLE.id, true/false)`.

---

## Data — Lists

Lists stored on targets keyed by ID. `LIST_ITEM_LIMIT = 200000`.

### `data_listcontents`
- **BlockType**: reporter
- **Arguments**: `[LIST: field_dropdown]`
- **Returns**: In monitor mode → `list.value` if `_monitorUpToDate`, else `list.value.slice()` copy. In non-monitor mode: if ALL items are single-char strings, join with `''`; else join with `' '`.

### List mutation commands

| Opcode | Extra args | Semantics |
|--------|-----------|-----------|
| `data_addtolist` | `ITEM` | Push ITEM to `list.value` if below limit. Sets `_monitorUpToDate = false`. |
| `data_deleteoflist` | `INDEX` | `Cast.toListIndex`. Invalid → no-op. `"all"` → clear. Else `splice(index-1, 1)`. |
| `data_deletealloflist` | — | `list.value = []`. |
| `data_insertatlist` | `ITEM, INDEX` | Insert at `index-1`. If insert exceeds limit, pop last. |
| `data_replaceitemoflist` | `ITEM, INDEX` | `list.value[index-1] = ITEM`. |
| `data_itemoflist` | `INDEX` | Returns `list.value[index-1]` or `''` if invalid. |
| `data_itemnumoflist` | `ITEM` | Uses `Cast.compare` for equality (cross-type). Returns 1-based index or `0`. |
| `data_lengthoflist` | — | Returns `list.value.length`. |
| `data_listcontainsitem` | `ITEM` | First checks `indexOf`, then iterates with `Cast.compare`. Returns `true` if any match. |
| `data_showlist` / `data_hidelist` | — | `changeMonitorVisibility(args.LIST.id, bool)`. |

---

## Sensing

### `sensing_touchingobject`
- **BlockType**: Boolean. Hidden on stage.
- **Inputs**: `[TOUCHINGOBJECTMENU: menu]` — `_mouse_`, `_edge_`, sprite names.
- **Semantics**: `util.target.isTouchingObject(args.TOUCHINGOBJECTMENU)`.

### `sensing_touchingcolor`
- **BlockType**: Boolean. Hidden on stage.
- **Inputs**: `[COLOR: colour_picker]`.
- **Semantics**: Color converted via `Cast.toRgbColorList`.

### `sensing_coloristouchingcolor`
- **Inputs**: `[COLOR: colour_picker, COLOR2: colour_picker]`.

### `sensing_distanceto`
- **BlockType**: Reporter. Hidden on stage.
- **Inputs**: `[DISTANCETOMENU: menu]` — `_mouse_`, sprite names.
- **Semantics**: `sqrt(dx² + dy²)`. Returns `10000` if stage or target not found.

### `sensing_timer`
- **BlockType**: Reporter, no inputs. Monitorable (id: `'timer'`).

### `sensing_resettimer`
- **BlockType**: command. Resets project timer to 0.

### `sensing_of`
- **BlockType**: Reporter.
- **Inputs**: `[OBJECT: menu]` — `_stage_`, sprite names.
- **Fields**: `[PROPERTY: dropdown]` — dynamic based on selected OBJECT.
  - Stage: `backdrop #`, `backdrop name`, `volume` + stage variables.
  - Sprite: `x position`, `y position`, `direction`, `costume #`, `costume name`, `size`, `volume` + sprite-local variables.
- **Returns** `0` if target not found or attribute not recognized.

### `sensing_mousex` / `sensing_mousey`
- **BlockType**: Reporter, no inputs.
- **Returns**: Mouse position in Scratch coordinates.

### `sensing_mousedown`
- **BlockType**: Boolean, no inputs.

### `sensing_keypressed`
- **BlockType**: Boolean.
- **Inputs**: `[KEY_OPTION: menu]`.
- **Semantics**: Returns true if specified key is pressed.

### `sensing_current`
- **BlockType**: Reporter.
- **Fields**: `[CURRENTMENU: dropdown]` — year, month, date, dayofweek, hour, minute, second.
- **Returns**: Current date/time component. Day of week: 1=Sunday.

### `sensing_dayssince2000`
- **BlockType**: Reporter, no inputs.
- **Semantics**: `(now - Jan 1 2000 00:00:00 UTC) / msPerDay`. Accounts for DST via timezone offset.

### `sensing_loudness` / `sensing_loud`
- `loudness`: Reporter. Returns microphone level or `-1`.
- `loud`: Boolean. `loudness > 10`.

### `sensing_askandwait`
- **Inputs**: `[QUESTION: input_value]` (shadow: text).
- **Semantics**: Asks question, queues if rapid succession. Waits for ANSWER event. Shows say bubble for visible sprites. Returns Promise.

### `sensing_answer`
- **BlockType**: Reporter, no inputs.
- **Returns**: Last answer to ask-and-wait.

### `sensing_setdragmode`
- **Fields**: `[DRAG_MODE: dropdown]` — `["draggable", "draggable"]`, `["not draggable", "not draggable"]`.

### `sensing_online` / `sensing_username` / `sensing_userid`
- `online`: `window.navigator.onLine`.
- `username`: From userData service.
- `userid`: Legacy no-op.

---

## Procedures

### `procedures_definition`
- Hat block (no-op). Body executes via runtime. `procedures_prototype` child carries mutation metadata.

### `procedures_call`
- Looks up definition by proccode, parses `argumentids`/`argumentnames`/`argumentdefaults`, builds `params` dict from call args + defaults, calls `util.startProcedure(proccode, params)`.

### `argument_reporter_string_number` / `argument_reporter_boolean`
- **BlockType**: reporter.
- Returns `util.getParam(args.VALUE)`. If not found (e.g. called outside a procedure), returns `0`.

---

## Input Format (SB3 JSON)

Input values in the SB3 JSON are arrays with a **shadow-flag prefix**:

| Format | Meaning |
|--------|---------|
| `[1, value]` | **Same block+shadow** — block and shadow are the same block (unobscured shadow). `value` is a literal or a compact primitive array. |
| `[2, value]` | **Block, no shadow** — a reporter block reference. `value` is a block ID or compact primitive array. |
| `[3, block, shadow]` | **Different block and shadow** — an obscured shadow. `block` is the reporter block ID, `shadow` is the shadow block ID/primitive. |

Where `value` / `block` / `shadow` can be:

- A **literal** (number, string, boolean) — the shadow's default value
- A **block ID string** (e.g. `"abc123"`) — reference to a top-level block
- A **compact primitive array** `[type_code, value, ...]` — an inlined primitive block (see below)

### Compact primitive type codes

These type codes replace full block objects for common primitives. The first element is the type code, the second is the field value:

| Code | Constant name | Opcode | Field | Extra elements |
|------|--------------|--------|-------|---------------|
| `4` | `MATH_NUM_PRIMITIVE` | `math_number` | `NUM` = value | — |
| `5` | `POSITIVE_NUM_PRIMITIVE` | `math_positive_number` | `NUM` = value | — |
| `6` | `WHOLE_NUM_PRIMITIVE` | `math_whole_number` | `NUM` = value | — |
| `7` | `INTEGER_NUM_PRIMITIVE` | `math_integer` | `NUM` = value | — |
| `8` | `ANGLE_NUM_PRIMITIVE` | `math_angle` | `NUM` = value | — |
| `9` | `COLOR_PICKER_PRIMITIVE` | `colour_picker` | `COLOUR` = value | — |
| `10` | `TEXT_PRIMITIVE` | `text` | `TEXT` = value | — |
| `11` | `BROADCAST_PRIMITIVE` | `event_broadcast_menu` | `BROADCAST_OPTION` = value | `[3]: id` |
| `12` | `VAR_PRIMITIVE` | `data_variable` | `VARIABLE` = name, `id` = id | `[3]: id`, `[4]: x`, `[5]: y` (topLevel only) |
| `13` | `LIST_PRIMITIVE` | `data_listcontents` | `LIST` = name, `id` = id | `[3]: id`, `[4]: x`, `[5]: y` (topLevel only) |

Examples:
```
[1, 10]              → shadow with literal value 10 (a math_number)
[1, [4, 10]]         → shadow with compact math_number(value=10)
[2, "block_abc"]     → reference to block "block_abc", no shadow
[2, [12, "score", "v1"]]  → reference to variable "score" (id=v1)
[3, "block_abc", [4, 0]]  → reporter "block_abc" with shadow math_number(default=0)
```

> **Top-level entries:** A compact primitive array may also appear **directly as a value in a target's `blocks` dict** (not wrapped in an input), e.g. `{"varBlockId": [12, "score", "v1", 150, 50]}`. Only codes `12`/`13` survive serialization as top-level entries — floating variable/list monitors. `deserializeBlocks` expands these into full block objects under a fresh `uid()` (the original key is discarded); other codes appearing at top level are deleted as an orphaned-shadow workaround (scratch-vm#1011). See *Top-level primitive blocks* in vm-reference.md.
