# Scratch VM Architecture Reference

> Extracted from [scratch-editor/scratch-vm](https://github.com/scratchfoundation/scratch-vm).

## 0. Fundamental Concepts

### Block Types (by Shape)

Blocks in Scratch are categorized by shape, which determines where they can be placed:

```
  ┌───────────────────────┐
  │  when ⚑ clicked       │  ← HAT: rounded top, starts execution
  │  when [space] pressed │     Lives on the editor canvas (topLevel=true).
  └───────────────────────┘     Execution begins at the block's `next`.

  ┌──────────────────────┐
  │  move 10 steps       │  ← STACK: notch on top, bump on bottom
  │  turn ↻ 15 degrees   │     Connects via `next`/`parent` links.
  │  say [hello]         │     The basic instruction block.
  └──────────────────────┘

  ┌──────────────────────┐
  │  repeat 10           │  ← C-SHAPED: wraps other blocks inside
  │  ┌──────────────┐    │     Has a SUBSTACK input slot.
  │  │  move 10     │    │     e.g. repeat, forever, if, if-else.
  │  └──────────────┘    │
  └──────────────────────┘

  ┌──────────────────────┐
  │  stop [all]          │  ← CAP: bump on top, flat bottom
  └──────────────────────┘     Ends a script. No `next` block.

  ┌──────────┐                ┌──────┐
  │  (5 + 3) │                │  <>  │  ← BOOLEAN: hexagonal
  └──────────┘                └──────┘     Fits in boolean inputs.
       ↑                          ↑
    REPORTER (oval)            BOOLEAN (hexagon)
    Returns a value.           Returns true/false.
    Fits in any input slot.    Fits only in boolean-shaped inputs.
```

### Block Relationships

```
     ┌──────────────────────────────────────────────┐
     │  when ⚑ clicked         ← HAT, topLevel     │
     │                          id: "hat1"          │
     └────────────┬─────────────────────────────────┘
                  │ next: "repeat1"
     ┌────────────▼─────────────────────────────────┐
     │  repeat (10)             ← C-SHAPED          │
     │                          id: "repeat1"       │
     │                          parent: "hat1"      │
     │  ┌─────────────────────┐                     │
     │  │  move 10 steps     │ ← SUBSTACK block    │
     │  │  id: "move1"       │   id referenced in  │
     │  │  parent: "repeat1" │   repeat1.inputs    │
     │  │  next: "bounce1"   │   .SUBSTACK.block   │
     │  └─────────────────────┘                     │
     │  ┌─────────────────────┐                     │
     │  │  if on edge, bounce │ ← next block in    │
     │  │  id: "bounce1"     │   substack chain    │
     │  │  parent: "repeat1" │                     │
     │  └─────────────────────┘                     │
     └──────────────────────────────────────────────┘
                  │ next: "wait1"
     ┌────────────▼─────────────────────────────────┐
     │  wait (0.1)  seconds   ← after the C-block   │
     │  id: "wait1"                                  │
     │  parent: "repeat1"                            │
     └──────────────────────────────────────────────┘

     Reporter plugged into an input:
     ┌──────────────────────────────────────────────┐
     │  move ( <...> ) steps    ← reporter input    │
     │         │                                     │
     │         │ inputs.STEPS.block: "add1"          │
     │  ┌──────▼──────┐                              │
     │  │  (5 + 3)    │ ← reporter block (oval)     │
     │  │  id: "add1" │   evaluated before move      │
     │  │  parent: "move1"│  executes                 │
     │  └─────────────┘                              │
     └──────────────────────────────────────────────┘
```

**Key relationships:**
- `next` / `parent` — linked list chain for sequential blocks. A block's `parent` is the block that points to it via `next` or an input. `next` is the block that runs after this one.
- `inputs[name].block` — a reporter or substack block plugged into an input slot. Evaluated before the parent block executes.
- `inputs[name].shadow` — the default placeholder block that appears when no reporter is plugged in. Only serialized; the runtime resolves through it if `.block` is null.
- Hat blocks have `topLevel: true` and are the entry points for threads.

### Stage vs Sprite

```
                    ┌──────────────────────────────┐
                    │  STAGE                        │
                    │  isStage = true               │
                    │  Size: 480 × 360 Scratch px   │
                    │                               │
                    │  ┌── Sprite ──────────────┐   │
                    │  │  isStage = false        │   │
                    │  │  x, y, direction, size  │   │
                    │  │  visible, layer_order   │   │
                    │  │  costumes, sounds       │   │
                    │  │  variables, lists       │   │
                    │  └─────────────────────────┘   │
                    │                               │
                    │     Shared across sprites:     │
                    │     - Stage variables ("global")│
                    │     - Backdrops (stage costumes)│
                    │     - Timer                    │
                    │     - Mouse position           │
                    └──────────────────────────────┘
```

| Property | Stage | Sprite |
|----------|-------|--------|
| Position | Fixed at (0,0) | Movable via x, y |
| Direction | N/A | 0=up, 90=right |
| Costumes | Called "backdrops" | Regular costumes |
| Motion blocks | Not available | Available |
| `isStage` | `true` | `false` |
| Toolbox | Event, control, sensing, operators, data, pen, looks (backdrop-specific) | All categories |

## 1. Key Data Structures

### Block

A node in the block tree. Blocks form a **linked list** via `next`/`parent` for sequential execution (`block.next` chains), and reference child blocks (reporters, substacks) through `inputs`.

| Field | JS Type | Meaning |
|-------|---------|---------|
| `id` | `string` | Unique block identifier (UUID). |
| `opcode` | `string` | Maps to handler (e.g. `"motion_movesteps"`). |
| `next` | `string \| null` | Block ID of the next block in the chain; `null` = end. |
| `parent` | `string \| null` | Block ID of the containing block. |
| `inputs` | `Object<string, InputInfo>` | Named input slots, each `{name, block, shadow}`. |
| `fields` | `Object<string, Field>` | Named field slots — dropdowns, variable pickers. |
| `shadow` | `boolean` | Whether this is a shadow (editor placeholder / menu block). |
| `topLevel` | `boolean` | Whether this block sits on the editor canvas. |
| `mutation` | `object \| null` | Procedure metadata (proccode, argument ids/names/defaults, warp). |
| `x`, `y` | `number \| null` | Editor position (topLevel only). |

> **Why "hat"?** Hat blocks have a rounded top in the editor, shaped like a hat. Stack blocks snap into the notch below. The term is used throughout: `startHats()`, `getHats()`, `edgeActivatedHats`. Hats have `"topLevel": true`.

**Block tree structure:**
```
event_whenflagclicked (topLevel=true)
  next → "block2"
           block2: control_repeat
             inputs.TIMES → {block: math_number_shadow, shadow: math_number_shadow}
             inputs.SUBSTACK → {block: motion_movesteps}
```

### InputInfo

Each input slot is a `{name, block, shadow}` object in the runtime. In SB3 JSON it serializes as `[shadowFlag, blockId, ?shadowId]`.

| Field | Type | Meaning |
|-------|------|---------|
| `name` | `string` | Logical slot name (e.g. `"STEPS"`, `"SUBSTACK"`). |
| `block` | `string \| null` | Block ID of the reporter or substack block plugged into this input. |
| `shadow` | `string \| null` | Block ID of the shadow block (the editor's default placeholder). |

### Field

A dropdown/field on a block (variable name, operator choice, colour picker, etc.).

| Field | Type | Meaning |
|-------|------|---------|
| `name` | `string` | Field key (e.g. `"VARIABLE"`, `"EFFECT"`, `"STYLE"`). |
| `value` | `any` | The selected value. |
| `id` | `string \| undefined` | Variable/list/broadcast ID for cross-referencing. |
| `variableType` | `string \| undefined` | `""` (scalar), `"list"`, or `"broadcast_msg"`. Not serialized; recovered by field name convention. |

### Mutation

Procedure metadata passed through Blockly's mutation system verbatim.

| Field | Type | Meaning |
|-------|------|---------|
| `tagName` | `string` | Always `"mutation"`. |
| `proccode` | `string` | Procedure signature (e.g. `"myBlock %n %s"`). |
| `argumentids` | `string` | JSON array of argument UUIDs. |
| `argumentnames` | `string` | JSON array of argument display names. |
| `argumentdefaults` | `string` | JSON array of default values. |
| `warp` | `string` | `"true"` = run without screen refresh. |

### Thread

Represents one execution path. scratch-vm's `Thread` class (`src/engine/thread.js`):

| Field | Type | Meaning |
|-------|------|---------|
| `target` | `Target` | The sprite/stage this thread runs on. |
| `topBlock` | `string` | Block ID of the first block. |
| `status` | `number` | One of 5 status constants (see below). |
| `stack` | `Array<StackFrame>` | Call stack. |
| `stackFrame` | `?StackFrame` | Current top frame (shorthand). |
| `params` | `object` | Procedure parameter values for the current call. |
| `isInitialization` | `boolean` | Whether this is a freshly started thread (used by stop-for-target). |

**Thread status constants:**

| Constant | Value | Meaning |
|----------|-------|---------|
| `STATUS_RUNNING` | `0` | Default; thread is stepped normally. |
| `STATUS_PROMISE_WAIT` | `1` | Yielding until a Promise resolves. |
| `STATUS_YIELD` | `2` | Yielded this frame; will continue next frame (or within warp timer). |
| `STATUS_YIELD_TICK` | `3` | Yielded until next tick (frame). Cleared at start of each tick. |
| `STATUS_DONE` | `4` | Thread finished. |

### StackFrame

One level of block execution on a thread's stack:

| Field | Type | Meaning |
|-------|------|---------|
| `blockId` | `string` | Block currently executing. |
| `opcode` | `string` | Cached from block. |
| `reporter` | `string \| null` | Block ID of a waiting reporter (when evaluating nested reporters). |
| `executed` | `boolean` | Whether the primitive has been called at least once. |
| `warpTimer` | `number \| null` | Timer for warp-mode execution. |
| `isLoop` | `boolean` | Whether this is a loop frame (repeat, forever, etc.). |
| `params` | `object \| null` | Procedure parameters for this call. |
| `topFrame` | `boolean` | Shorthand for `stack.length === 1`. |
| `waitingReporter` | `boolean` | Whether the frame is waiting for a reporter result. |

Stack frames are managed by the sequencer: `pushStack(blockId)`, `popStack()`, `popToFrame()`, `goToNextBlock()`.

### Target

Represents a sprite or the stage (distinguished by `isStage`). The `Target` class (`src/engine/target.js`) extends `RenderedTarget`:

| Category | Key fields |
|----------|-----------|
| **Identity** | `id`, `isStage`, `isOriginal` (distinguishes the prototype from clones). |
| **Blocks** | `blocks: object` — block tree keyed by block ID. |
| **Data** | `variables: object`, `lists: object`, `broadcasts: object`. |
| **Visual** | `costumes`, `currentCostume`, `sounds`, `visible`, `volume`, `layerOrder`, `effects`. |
| **Motion** | `x`, `y`, `direction`, `size`, `rotationStyle`. |
| **Drawing** | `drawableId` (links to the RenderWebGL drawable). |
| **Bubble** | `sayText`, `sayBubbleId`, `sayBubbleType`. |

### Variable

Scratch's `Variable` class (`src/engine/variable.js`):

```javascript
class Variable {
    constructor(id, name, type, isCloud) {
        this.id = id;
        this.name = name;
        this.type = type || Variable.SCALAR_TYPE;
        this.isCloud = isCloud;
        this.value = 0;  // default
    }
}
Variable.SCALAR_TYPE = '';
Variable.LIST_TYPE = 'list';
Variable.BROADCAST_MESSAGE_TYPE = 'broadcast_msg';
```

Lists use the same `Variable` class with `type = 'list'` and `value` = array.

### Cloud Variables

Cloud variables are **stage-only** scalar variables synchronized with a server via WebSocket. They persist across sessions and are visible to all users of the same project.

**SB3 format:** the third element of the variable array is `true`:
```json
{"☁ score": ["☁ score", 100, true]}
```

**Loading** (`sb3.js` deserialization):
```javascript
const isCloud = (variable.length === 3) && variable[2] &&     // third element is true
    object.isStage &&                                           // must be on the stage
    runtime.canAddCloudVariable();                              // limit check (max 10)
if (isCloud) runtime.addCloudVariable();
newVariable.value = variable[1];
```

**Runtime limit:** max 10 cloud variables per project, enforced by `cloudDataManager()`:
```javascript
const cloudDataManager = () => {
    const limit = 10;
    let count = 0;
    return {
        canAddCloudVariable: () => count < limit,
        addCloudVariable: () => { count++; },
        removeCloudVariable: () => { count--; },
        hasCloudVariables: () => count > 0,
    };
};
```

**Update flow** (in `scratch3_data.js`):
```
data_setvariableto / data_changevariableby
  → variable.value = newValue
  → if variable.isCloud:
       util.ioQuery('cloud', 'requestUpdateVariable', [variable.name, newValue])
         → Cloud.requestUpdateVariable(name, value)
           → provider.updateVariable(name, value)    // WebSocket.send
```

**Incoming updates** are processed through `Cloud.postData(data)`:
```
WebSocket → provider → Cloud.postData({varUpdate: {name, value}})
  → updateCloudVariable(varUpdate)
    → stage.lookupVariableByName(name).value = value
```

The `Cloud` IO device (`src/io/cloud.js`) is a thin bridge:
- `setProvider(provider)` — connects a WebSocket provider (usually `scratch-cloud-provider`).
- `setStage(stage)` — the stage target that owns cloud variables.
- `requestUpdateVariable(name, value)` — delegates to provider.
- `requestCreateVariable(variable)` — checks limit before delegating.
- `updateCloudVariable(varUpdate)` — updates the variable on the stage target.

---

## 2. Scheduler & Execution Model

### Sequencer (`src/engine/sequencer.js`)

The sequencer drives thread execution. It is called from `Runtime._step()` once per frame.

#### `stepThreads()` — Outer Loop

```
Called from Runtime._step() each frame:
1. Reset STATUS_YIELD_TICK threads at the start of the first tick.
2. For each tick:
   - Iterate all threads (round-robin via while-loop).
   - Call stepThread(thread) for each active thread.
   - After a full tick, filter out STATUS_DONE threads.
3. Stop when:
   - All threads are blocked (YIELD/PROMISE_WAIT/WAITING), OR
   - WORK_TIME budget exceeded (75% of frame budget ≈ 12.5ms), OR
   - A redraw was requested AND not in turbo mode.
```

#### `stepThread(thread)` — Inner Loop

```
while (thread.peekStack() !== null):
  1. Check warp mode: if warp, start warpTimer.
  2. Call execute(this, thread) to run the current block's primitive.
  3. Inspect thread.status after execution:
     - STATUS_YIELD → reset to RUNNING.
       If warp mode and warpTimer < WARP_TIME (500ms): CONTINUE (no yield between blocks).
       Else: RETURN (yield to other threads).
     - STATUS_PROMISE_WAIT → RETURN (waiting for async).
     - STATUS_YIELD_TICK → RETURN (wait for next frame).
  4. If stack top unchanged (no control flow happened), call thread.goToNextBlock().
  5. If stack top is now null, pop the frame:
     - Stack empty → STATUS_DONE.
     - frame.isLoop → yield (unless warp mode and WARP_TIME not exceeded).
     - frame.waitingReporter → RETURN.
     - Otherwise → goToNextBlock() and continue.
```

Key design: the inner loop lets a single thread consume its whole stack in one invocation, yielding only at yield/promise/loop boundaries. This is different from a "one block per frame" model — blocks run sequentially until they hit a yield point.

#### `execute(sequencer, thread)` — Primitive Dispatch

```
1. Get current block from thread.target.blocks[frame.blockId].
2. If block has a `shadow` child instead of a real block, resolve through the shadow.
3. Call runtime.getOpcodeFunction(block.opcode)(args, util).
4. The primitive may:
   - Return undefined → instant completion, continue to next block.
   - Return a Promise → handlePromise sets STATUS_PROMISE_WAIT.
   - Call util.yield() → set STATUS_YIELD.
   - Call util.yieldTick() → set STATUS_YIELD_TICK.
   - Complete control flow → push/pop stack frames.
```

#### `startBranch(branchNum, loopFlag)` — Substack Execution

Control blocks (repeat, if, forever) use `startBranch` to execute their substack:

1. `branchNum` = 1 or 2 (for if-else).
2. `loopFlag` = true if the frame should loop (repeat, forever, while).
3. Pushes a new stack frame pointing to the substack input's first block.
4. Returns to `stepThread`, which calls `execute` on the substack block.
5. When the substack is done (stack pops back to the control block), the control block's `executed` flag is checked:
   - Loop blocks → re-enter (the primitive runs again).
   - Non-loop blocks → done.

### `Runtime._step()` — One Frame

```
Runtime._step():
  1. Process wait queue: wake threads whose timer has expired.
  2. Call sequencer.stepThreads() to run all active threads.
  3. Fire edge-activated hats via updateEdgeHats().
  4. Advance the clock.
```

The frame rate is controlled by `setInterval` at `THREAD_STEP_INTERVAL` (≈16.7ms for 60fps, or 33.3ms in compatibility mode).

### Block Chaining

`thread.goToNextBlock()` moves to `block.next`:
- If `block.next` exists → replace `frame.blockId` with next, reset `frame.executed` to `false`.
- Else → `popStack()`. If stack empty → `STATUS_DONE`.

This implements Scratch's linked-list chains: sequential blocks occupy one stack level, replacing each other. Reporters and control substacks push additional frames.

### Warp Mode

Warp mode is a performance optimization for **procedure definitions** (`procedures_definition` blocks) marked with `mutation.warp = "true"`. It suppresses intra-frame yields so the procedure runs as fast as possible, up to a 500ms budget.

**Why it exists:** Scratch's "run without screen refresh" checkbox on custom blocks. Without warp mode, each iteration of a loop yields control back to the sequencer, allowing other threads to run and the screen to refresh. With warp mode, the loop iterates continuously until the 500ms budget is exhausted.

**How it works (sequencer.js):**

```
stepThread(thread):
  stackFrame = thread.peekStackFrame()
  isWarpMode = stackFrame.warpMode

  if isWarpMode && !thread.warpTimer:
    thread.warpTimer = new Timer(); thread.warpTimer.start()

  loop:
    execute(sequencer, thread)

    if thread.status === STATUS_YIELD:
      thread.status = STATUS_RUNNING
      if isWarpMode && warpTimer.elapsed() <= WARP_TIME (500ms):
        continue  ← DON'T yield to other threads, keep running
      return     ← yield normally

    if stack pops and frame.isLoop:
      if isWarpMode && warpTimer.elapsed() <= WARP_TIME:
        continue  ← DON'T yield between iterations
      return     ← yield normally
```

**Key behaviors:**
- `WARP_TIME = 500ms` — caps warp mode to prevent complete VM freeze.
- `STATUS_YIELD` is swallowed (reset to `RUNNING`) within the warp budget.
- Loop frames (`isLoop = true`) don't yield between iterations within the budget.
- `STATUS_YIELD_TICK` and `STATUS_PROMISE_WAIT` are NOT affected — async blocks (wait, play-until-done) still pause.
- The `warpTimer` is initialized once per thread at the first warp-mode `stepThread` call, and **reset to null** at the start of each frame's `stepThreads()` loop (line 129).

**Activation:** Set during `startProcedure`:
```
startProcedure(thread, definition):
  push definition body onto stack
  read definition's mutation.warp
  if warp: stackFrame.warpMode = true
```

**py-scratch status:** Not implemented. `Mutation.warp` is parsed from SB3 but never acted on. All blocks yield normally regardless of the warp flag.

## 3. Thread Status Protocol

Primitives control the scheduler by setting `thread.status`. There is no yielded-value protocol — the primitive returns `void` and the sequencer inspects `thread.status` afterwards:

| Status | Set by | Sequencer action |
|--------|--------|------------------|
| `STATUS_RUNNING` (0) | Default | No special action. |
| `STATUS_PROMISE_WAIT` (1) | `handlePromise()` when primitive returns a Promise | Return; resume when Promise resolves. |
| `STATUS_YIELD` (2) | `util.yield()` | Reset to RUNNING; if warp + timer < 500ms continue, else return. |
| `STATUS_YIELD_TICK` (3) | `util.yieldTick()` | Return; cleared at start of next `stepThreads()` tick. |
| `STATUS_DONE` (4) | Sequencer when stack empties | Filtered out by `stepThreads()`. |

For async blocks (like `play sound * until done`, `ask * and wait`, `say * for * seconds`), the primitive returns a `Promise`. The sequencer's `handlePromise` stores the resolve/reject callbacks and sets `STATUS_PROMISE_WAIT`. When the Promise resolves, status is set back to `RUNNING`.

---

## 4. Hat & Event System

### Hat Index

`Runtime._hatIndex: Map<string, {target: Target, blockId: string}[]>` — maps opcode strings to `(target, blockId)` pairs. Populated by `_registerTarget(target)` on `addTarget`.

### Hat Activation

`runtime.startHats(opcode, optMatchFields, optTarget)`:
1. Look up `opcode` in `_hatIndex`.
2. For edge-activated hats, check edge state first.
3. For `restartExistingThreads: true` hats, stop existing threads for this hat+target.
4. Create a new `Thread` starting from the hat's `next` block, or the hat itself if no `next`.
5. If `optMatchFields` provided, filter by matching field values (used by broadcast).
6. Returns the list of started threads.

### Green Flag

`runtime.greenFlag()`:
1. Stop all threads (`disposeAllThreads`).
2. Clear all edge-hat state (`_edgeActivatedHatValues`).
3. Call `startHats('event_whenflagclicked')`.

### Edge-Activated Hats

Edge-activated hats (like `event_whentouchingobject`, `event_whengreaterthan`) only fire on **false → true** transition:

1. The hat's primitive returns the current boolean value.
2. `updateEdgeHats()` is called each frame after `stepThreads()`:
   - For each registered edge-activated opcode in `_hatIndex`, evaluate the hat's primitive.
   - Compare against the stored value in `_edgeActivatedHatValues`.
   - If previous was falsy and current is truthy → call `startHats`.

Edge-hat state is stored keyed by `opcode:targetId:blockId`.

### Broadcast

`event_broadcast`:
- Resolve `BROADCAST_INPUT` to get the message string (looked up by broadcast id or name).
- Call `runtime.startHats('event_whenbroadcastreceived', {BROADCAST_OPTION: message})`.

`event_broadcastandwait`:
- Same as broadcast, but remembers the started threads in `stackFrame.startedThreads`.
- Yields (returns a Promise that resolves when all started threads finish).

### Key Press

`runtime.postIOData('keyboard', {keyName, isDown})`:
- Subscribe to `KEY_PRESSED` event in the event hat constructor.
- Start hats for both exact key match and `'any'` wildcard.

### Sprite/Stage Click

`runtime.postIOData('mouse', {x, y, isDown})`:
- The GUI calls `runtime.startHats('event_whenthisspriteclicked', {}, target)` for the clicked sprite.
- Falls through to `event_whenstageclicked` if no sprite hit.

---

## 5. Input Resolution & Type System

### Primitive Arguments (`args` object)

The sequencer resolves block inputs into an `args` object before calling the primitive. For each input on the block:

1. **Input has a `block` reference**: evaluate the reporter block via `evaluate(target, blockId)` → synchronous reporter chain.
2. **Input has no `block`**: use the shadow block's field value.
3. **Field values** are passed through directly.

### Runtime `evaluate(target, blockId)` — Reporter Evaluation

```
1. Get block by ID.
2. Look up handler for block.opcode.
3. Call handler(args, util):
   - Reporter handlers return a value directly.
   - If the handler is a generator (old-style), iterate it to collect Report(value).
4. Return the value.
```

Reporters are evaluated synchronously and never wait. This is atomic within a frame.

### Casting Utilities (`src/util/cast.js`)

All primitives cast input values through these functions:

| Function | Behavior | Edge cases |
|----------|----------|------------|
| `Cast.toNumber(v)` | `Number(v)`. If NaN → 0. | `NaN` → `0`, `undefined` → `0`, `true` → `1`, `"Infinity"` → `Infinity`, `"hello"` → `0`, `[3]` → `3` |
| `Cast.toString(v)` | `String(v)` | `null` → `"null"`, `undefined` → `"undefined"` |
| `Cast.toBoolean(v)` | Falsy: `""`, `"0"`, `"false"` (CI), `0`, `NaN`, `null`, `undefined` | `"false"` → `false` (JS: `true`), `" "` → `true`, `[]` → `true` |
| `Cast.compare(v1, v2)` | Three-way. If both whitespace/null → NaN (string compare). If either NaN → CI string compare. Else numeric. | `compare(0, "")` > 0 (whitespace forces string path) |
| `Cast.toListIndex(v, len)` | `"all"` → `LIST_ALL`, `"last"` → len, `"random"` → random 1-index, else numeric floor | Only for non-number types |


### Block Shadow Input Resolution

When the sequencer calls `evaluate` for a block, if the block is a primitive shadow (math_number, text, variable getter, etc.), it returns the field value directly rather than executing a handler. This is handled by `Runtime.getOpcodeFunction` which maps primitives to value-returning functions.

---

## 6. Clone System

```
runtime.makeClone(target):
  1. If target.isOriginal: clone = target.makeClone() → shallow copy.
  2. clone.isOriginal = false.
  3. runtime.addTarget(clone):
     - Insert into render order (behind the original).
     - Register the clone's drawable.
     - Index hat blocks.
  4. Start hats: event_whenflagclicked, event_whenthisspriteclicked, control_start_as_clone.
  5. Return clone.

runtime.disposeTarget(target):
  1. Disconnect the render drawable.
  2. Remove from targets list.
  3. Stop all threads on this target (runtime.stopForTarget).
  4. If clone, remove from clones list.

Clones share blocks with the original (reference, not copy). Variables and lists are deep-copied during `makeClone()`.
```

### `control_start_as_clone`
- Hat block, `restartExistingThreads: false`.
- Fires when a clone is created. Started by `runtime.startHats('control_start_as_clone', {}, target)` in `makeClone`.

---

## 7. Procedure / Custom Block System

### Call Flow

```
procedures_call primitive (args, util):
  1. Get mutation from the call block → proccode, argumentids.
  2. Look up definition block by matching proccode.
  3. Parse argumentids / argumentnames / argumentdefaults from DEFINITION's mutation.
  4. Build params = {}:
     for each arg id in argumentids:
       if call block has this input → use resolved value from args[argId]
       else if a default exists → use default
       else → ""
  5. Mark `executed = true` (run only once per stack frame).
  6. util.startProcedure(proccode, params):
     - Sets thread.params = params (for argument reporters to find).
     - Pushes the definition body's first block onto the stack.
     - The sequencer continues stepping into the body.

argument_reporter_string_number / _boolean primitive (args, util):
  return util.getParam(args.VALUE)
  // Looks up the current procedure call's params on the thread.
  // If not found → return "" (string_number) or 0 (boolean).
```

### Procedure Definition

`procedures_definition` is a hat block. Its body (`next`) is the procedure code. The `procedures_prototype` child block carries the mutation metadata. During SB3 deserialization, the prototype's argument reporter children are deleted (recreated by Blockly's `domToMutation`).

### SB3 Mutation

Stored as `block.mutation` verbatim:

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

---

## 8. SB3 Serialization Format

Source: `src/serialization/sb3.js`.

### Input Format — Shadow/Block Relationship

Each input serializes as `[code, blockId, ?shadowId]`:

| Code | Constant | Meaning | Array |
|------|----------|---------|-------|
| `1` | `INPUT_SAME_BLOCK_SHADOW` | block === shadow | `[1, idOrPrimitive]` |
| `2` | `INPUT_BLOCK_NO_SHADOW` | no shadow (block only) | `[2, blockId]` |
| `3` | `INPUT_DIFF_BLOCK_SHADOW` | block and shadow differ | `[3, blockId, shadowId]` |

### Primitive Type Codes

Primitive shadows inline as `[typeCode, value, ...]` instead of full block objects:

| Code | Constant | Opcode | Field | Format |
|------|----------|--------|-------|--------|
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

Codes 4–13 intentionally overlap with 1–3 (disjoint contexts).

### Variable/List/Broadcast Encoding

```json
// Variables: {id: [name, value, ?isCloud]}
{"varId": ["score", 42], "cloudVarId": ["☁ score", 100, true]}

// Lists: {id: [name, [item1, item2, ...]]}
{"listId": ["inventory", ["sword", "shield"]]}

// Broadcasts: {id: name}
{"broadcastId": "message1"}
```

### Field Encoding

```json
// Simple field: {fieldName: [value]}
{"EFFECT": ["color"]}

// With id (variable, list, broadcast):
{"VARIABLE": ["my var", "varId123"]}
```

### Block Serialization

```json
{
  "opcode": "motion_movesteps",
  "next": "nextBlockId",
  "parent": "parentBlockId",
  "inputs": {"STEPS": [1, [4, "10"]]},
  "fields": {},
  "shadow": false,
  "topLevel": true,
  "x": 100,
  "y": 200,
  "mutation": { ... },
  "comment": "blockId_comment"
}
```

### Compression Pipeline

1. **Serialize each block**. Primitives → compact arrays.
2. **Compress** (`compressInputTree`): replace block IDs in inputs with inline primitive arrays. Delete orphaned primitive entries.
3. **Cleanup**: delete orphaned top-level primitive arrays (except VAR/LIST, which can be top-level).

Deserialization reverses this via `deserializeInputDesc`.

### Shadow Repair

After deserialization, a third pass repairs missing/broken shadows:
- Detects `shadowIsBroken` (ID points to nonexistent block) and `shadowIsMissing` (null when it shouldn't be).
- Finds a peer block (same opcode + input) with a working shadow via `findPeerShadow`.
- Rebuilds the shadow using `buildShadowFields(shadowOpcode, template)`.

### Procedures Prototype

`procedures_prototype` input children (`argument_reporter_*`) are deleted during deserialization. Blockly recreates them from mutation data.

### Examples

```json
// Inline math_number shadow:
{"STEPS": [1, [4, "10"]]}

// Obscured shadow (reporter + shadow fallback):
{"VALUE": [3, "reporterBlockId", [7, "0"]]}

// Variable getter inline:
{"VARIABLE": [1, [12, "my var", "actualVarId"]]}

// Top-level variable monitor (in blocks dict):
{"varBlockId": [12, "my var", "actualVarId", 150, 50]}

// Broadcast inline:
{"BROADCAST_INPUT": [1, [11, "message1", "broadcastId"]]}
```
