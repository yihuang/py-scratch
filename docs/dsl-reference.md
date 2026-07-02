# Scratch DSL Reference

The `scratch.dsl` package is a Pythonic block builder for constructing Scratch 3
projects programmatically.  Expressions mirror the Scratch block structure in
Python code, and the builder produces valid `.sb3` files importable by the
Scratch editor.

## Quick start

```python
from scratch.dsl import Project, motion, control, looks, data, operators, sensing

project = Project("My Game")
sprite = project.sprite("Cat")
sprite.var("score", 0)

sprite.when_flag_clicked(
    control.forever()(
        motion.move(5),
        motion.if_on_edge_bounce(),
        control.wait(0.01),
    ),
)

sprite.when_key_pressed("space")(
    data.set_variable("score", operators.add(data.variable("score"), 1)),
    looks.say(operators.join("Score: ", data.variable("score"))),
)

project.save("game.sb3")
```

## Project and targets

### `Project(name="Project")`

Top-level entry point.  Manages the stage and all sprites.

| Method | Description |
|--------|-------------|
| `sprite(name) -> ProjectTarget` | Create and return a new sprite |
| `stage -> ProjectTarget` | The stage (unique, auto-created) |
| `build_runtime() -> Runtime` | Construct a Runtime and build all scripts |
| `save(path)` | Save as `.sb3` file (accepts `str`, `Path`, or `BytesIO`) |

### `ProjectTarget`

A sprite or the stage under construction.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `name` | `"Sprite"` | Display name |
| `x, y` | `0.0, 0.0` | Initial position |
| `direction` | `90.0` | Initial direction (0=up, 90=right) |
| `size` | `100.0` | Size percent |
| `visible` | `True` | Visibility |
| `layer_order` | `1` (sprites), `0` (stage) | Render order |

| Method | Description |
|--------|-------------|
| `var(name, default=0)` | Declare a variable (raises `ValueError` on duplicate) |
| `costume(name, ...)` | Add a costume (body args only, image auto-generated if needed) |
| `when_flag_clicked(*body)` | Register a green-flag script |
| `when_key_pressed(key)(*body)` | Register a key-press script |

## Expression types

### `StackExpr`

A command, hat, or C-shaped block.  The base for all stackable blocks.

- **Hat blocks** (`when_flag_clicked`, `when_key_pressed`) are entry points.
  They accept their body as positional arguments to the hat method on a target.
- **C-shaped blocks** (`repeat`, `forever`, `if_`, `if_else`) use `__call__` to
  attach their body and `.else_()` for the false branch of `if_else`.

```python
# Hat: body passed to the target method
sprite.when_flag_clicked(motion.move(10), looks.say("done"))

# C-shaped body via __call__
control.repeat(10)(motion.move(5))

# if_else with both branches
control.if_else(sensing.touching("edge"))(
    looks.say("ouch"),
).else_(
    motion.move(-10),
)
```

### `Reporter`

An oval or hexagonal block that produces a value.  Can be used as an argument
to any command block's input or nested inside another reporter.

```python
operators.add(data.variable("score"), 1)
operators.join("Score: ", data.variable("score"))
sensing.touching("edge")
```

## Category reference

### Motion

| Function | Opcode | Inputs/Fields |
|----------|--------|---------------|
| `move(steps=10)` | `motion_movesteps` | `STEPS` |
| `turn_right(degrees=15)` | `motion_turnright` | `DEGREES` |
| `turn_left(degrees=15)` | `motion_turnleft` | `DEGREES` |
| `goto(x=0, y=0)` | `motion_gotoxy` | `X, Y` |
| `glide(secs=1, x=0, y=0)` | `motion_glidesecstoxy` | `SECS, X, Y` |
| `glide_to(random_position=None)` | `motion_glideto` | Field: `TO` |
| `set_x(x=0)` | `motion_setx` | `X` |
| `set_y(y=0)` | `motion_sety` | `Y` |
| `change_x(dx=10)` | `motion_changexby` | `DX` |
| `change_y(dy=10)` | `motion_changeyby` | `DY` |
| `if_on_edge_bounce()` | `motion_ifonedgebounce` | — |
| `set_rotation_style(style)` | `motion_setrotationstyle` | Field: `STYLE` |
| `set_direction(direction=90)` | `motion_setdirection` | `DIRECTION` |
| `point_towards(towards)` | `motion_pointtowards` | Field: `TOWARDS` |
| `x_position()` | `motion_xposition` | Reporter |
| `y_position()` | `motion_yposition` | Reporter |
| `direction()` | `motion_direction` | Reporter |

### Looks

| Function | Opcode | Inputs/Fields |
|----------|--------|---------------|
| `say(message="")` | `looks_say` | `MESSAGE` |
| `say_for_seconds(message, secs=2)` | `looks_sayforsecs` | `MESSAGE, SECS` |
| `think(message="")` | `looks_think` | `MESSAGE` |
| `think_for_seconds(message, secs=2)` | `looks_thinkforsecs` | `MESSAGE, SECS` |
| `show()` | `looks_show` | — |
| `hide()` | `looks_hide` | — |
| `switch_costume_to(costume)` | `looks_switchcostumeto` | Field: `COSTUME` |
| `next_costume()` | `looks_nextcostume` | — |
| `switch_backdrop_to(backdrop)` | `looks_switchbackdropto` | Field: `BACKDROP` |
| `next_backdrop()` | `looks_nextbackdrop` | — |
| `change_effect(effect, change=25)` | `looks_changeeffectby` | Input: `CHANGE`, Field: `EFFECT` |
| `set_effect(effect, value=0)` | `looks_seteffectto` | Input: `VALUE`, Field: `EFFECT` |
| `clear_effects()` | `looks_cleargraphiceffects` | — |
| `change_size_by(change=10)` | `looks_changesizeby` | `CHANGE` |
| `set_size_to(size=100)` | `looks_setsizeto` | `SIZE` |
| `change_volume_by(change=10)` | `looks_changevolumeby` | `VOLUME` |
| `set_volume_to(volume=100)` | `looks_setvolumeto` | `VOLUME` |
| `costume_number_name()` | `looks_costumenumbername` | Reporter |
| `size()` | `looks_size` | Reporter |
| `volume()` | `looks_volume` | Reporter |

### Control

| Function | Opcode | Description |
|----------|--------|-------------|
| `repeat(times=10)` | `control_repeat` | C-shaped; body via `__call__` |
| `forever()` | `control_forever` | C-shaped; body via `__call__` |
| `if_(condition)` | `control_if` | C-shaped; body via `__call__` |
| `if_else(condition)` | `control_if_else` | C-shaped; true branch via `__call__`, false via `.else_()` |
| `wait(duration=1)` | `control_wait` | Pause for `duration` seconds |
| `stop(option="all")` | `control_stop` | Field: `STOP_OPTION` |
| `repeat_until(condition)` | `control_repeat_until` | C-shaped |
| `wait_until(condition)` | `control_wait_until` | — |
| `create_clone_of(sprite)` | `control_create_clone_of` | Field: `CLONE_OPTION` |
| `delete_this_clone()` | `control_delete_this_clone` | — |
| `all_at_once()` | `control_all_at_once` | C-shaped (warp mode) |

### Events

| Function | Opcode | Description |
|----------|--------|-------------|
| `when_flag_clicked()` | `event_whenflagclicked` | Hat |
| `when_key_pressed(key="space")` | `event_whenkeypressed` | Hat; Field: `KEY_OPTION` |
| `when_this_sprite_clicked()` | `event_whenthisspriteclicked` | Hat |
| `when_backdrop_switches_to(backdrop)` | `event_whenbackdropswitchesto` | Hat; Field: `BACKDROP` |
| `when_greater_than(metric, value)` | `event_whengreaterthan` | Hat; Field: `WHENGREATERTHAN_MENU` |
| `when_broadcast_received(message)` | `event_whenbroadcastreceived` | Hat; Field: `BROADCAST_OPTION` |
| `broadcast(message)` | `event_broadcast` | Field: `BROADCAST_OPTION` |
| `broadcast_and_wait(message)` | `event_broadcastandwait` | Field: `BROADCAST_OPTION` |

### Data (Variables & Lists)

| Function | Opcode | Inputs/Fields |
|----------|--------|---------------|
| `set_variable(variable, value=0)` | `data_setvariableto` | Input: `VALUE`, Field: `VARIABLE` |
| `change_variable(variable, change=1)` | `data_changevariableby` | Input: `VALUE`, Field: `VARIABLE` |
| `show_variable(variable)` | `data_showvariable` | Field: `VARIABLE` |
| `hide_variable(variable)` | `data_hidevariable` | Field: `VARIABLE` |
| `variable(variable)` | `data_variable` | Reporter; Field: `VARIABLE` |
| `add_to_list(list_, item)` | `data_addtolist` | Input: `ITEM`, Field: `LIST` |
| `delete_of_list(list_, index=1)` | `data_deleteoflist` | Input: `INDEX`, Field: `LIST` |
| `insert_at_list(list_, item, index=1)` | `data_insertatlist` | Inputs: `ITEM, INDEX`, Field: `LIST` |
| `replace_item_of_list(list_, index, item)` | `data_replaceitemoflist` | Inputs: `INDEX, ITEM`, Field: `LIST` |
| `item_of_list(list_, index=1)` | `data_itemoflist` | Reporter; Input: `INDEX`, Field: `LIST` |
| `length_of_list(list_)` | `data_lengthoflist` | Reporter; Field: `LIST` |
| `list_contains_item(list_, item)` | `data_listcontainsitem` | Reporter; Input: `ITEM`, Field: `LIST` |

### Operators

| Function | Opcode | Returns |
|----------|--------|---------|
| `add(a, b)` | `operator_add` | Number |
| `sub(a, b)` | `operator_subtract` | Number |
| `mult(a, b)` | `operator_multiply` | Number |
| `div(a, b)` | `operator_divide` | Number |
| `random(from_, to)` | `operator_random` | Number |
| `gt(a, b)` | `operator_gt` | Boolean |
| `lt(a, b)` | `operator_lt` | Boolean |
| `eq(a, b)` | `operator_equals` | Boolean |
| `and_(a, b)` | `operator_and` | Boolean |
| `or_(a, b)` | `operator_or` | Boolean |
| `not_(a)` | `operator_not` | Boolean |
| `join(a, b)` | `operator_join` | String |
| `letter_of(letter, string)` | `operator_letter_of` | String |
| `length(string)` | `operator_length` | Number |
| `contains(string, substring)` | `operator_contains` | Boolean |
| `mod(a, b)` | `operator_mod` | Number |
| `round_(n)` | `operator_round` | Number |
| `sqrt(n)` | `operator_mathop` with `sqrt` | Number |
| `abs_(n)` | `operator_mathop` with `abs` | Number |
| `floor_(n)` | `operator_mathop` with `floor` | Number |
| `ceil_(n)` | `operator_mathop` with `ceil` | Number |
| `sin(n)` | `operator_mathop` with `sin` | Number |
| `cos(n)` | `operator_mathop` with `cos` | Number |
| `tan(n)` | `operator_mathop` with `tan` | Number |
| `asin(n)` | `operator_mathop` with `asin` | Number |
| `acos(n)` | `operator_mathop` with `acos` | Number |
| `atan(n)` | `operator_mathop` with `atan` | Number |

### Sensing

| Function | Opcode | Inputs/Fields |
|----------|--------|---------------|
| `ask_and_wait(question)` | `sensing_askandwait` | `QUESTION` |
| `reset_timer()` | `sensing_resettimer` | — |
| `answer()` | `sensing_answer` | Reporter |
| `mouse_x()` | `sensing_mousex` | Reporter |
| `mouse_y()` | `sensing_mousey` | Reporter |
| `mouse_down()` | `sensing_mousedown` | Reporter |
| `key_pressed(key="space")` | `sensing_keypressed` | Reporter; Field/Input: `KEY_OPTION` |
| `touching(object="mouse pointer")` | `sensing_touchingobject` | Reporter; Field/Input: `TOUCHINGOBJECTMENU` |
| `touching_color(color)` | `sensing_touchingcolor` | Reporter; `COLOR` |
| `color_is_touching_color(color, other)` | `sensing_coloristouchingcolor` | Reporter; `COLOR, COLOR2` |
| `distance_to(object="mouse pointer")` | `sensing_distanceto` | Reporter; Field/Input: `DISTANCETOMENU` |
| `timer()` | `sensing_timer` | Reporter |
| `current(unit)` | `sensing_current` | Reporter; Field: `CURRENTMENU` |
| `days_since_2000()` | `sensing_dayssince2000` | Reporter |
| `loudness()` | `sensing_loudness` | Reporter |
| `username()` | `sensing_username` | Reporter |

### Pen

| Function | Opcode |
|----------|--------|
| `pen_down()` | `pen_penDown` |
| `pen_up()` | `pen_penUp` |
| `pen_clear()` | `pen_penClear` |
| `stamp()` | `pen_stamp` |
| `change_pen_color_by(change=10)` | `pen_changePenColorParamBy` |
| `set_pen_color_to(color=0)` | `pen_setPenColorParamTo` |
| `change_pen_shade_by(change=10)` | `pen_changePenColorParamBy` |
| `set_pen_shade_to(shade=50)` | `pen_setPenColorParamTo` |
| `change_pen_size_by(change=1)` | `pen_changePenSizeBy` |
| `set_pen_size_to(size=1)` | `pen_setPenSizeTo` |
| `pen_color(color="#000000")` | `pen_setPenColorToColor` |
| `pen_saturation(saturation=100)` | `pen_setPenColorParamTo` |
| `pen_brightness(brightness=100)` | `pen_setPenColorParamTo` |
| `pen_hue(hue=0)` | `pen_setPenColorParamTo` |

## Input conventions

### Positional vs keyword

Functions accept **positional args** for the primary input and **keyword args**
for secondary inputs or clarity::

```python
motion.move(10)                    # primary: steps
motion.goto(x=100, y=0)           # keyword for clarity
motion.glide(secs=1, x=100, y=0)  # mixed
```

### Literals vs reporters

Any input that accepts a number or string can also accept a ``Reporter`` object,
which creates a nested block reference::

```python
data.set_variable("score", 10)                                    # literal
data.set_variable("score", operators.add(data.variable("score"), 1))  # reporter
```

### Python keyword collisions

Functions whose names collide with Python keywords use a trailing underscore:

- `random(from_, to)` — `from` is reserved
- `and_(a, b)`, `or_(a, b)`, `not_(a)` — logical operators
- `if_(condition)` — control flow
- `list_` parameter in list functions

## Running and saving

```python
# Save as .sb3 (headless)
project.save("game.sb3")

# Run interactively with the pygame renderer
rt = project.build_runtime()
from scratch.vm.renderer import Renderer
renderer = Renderer(rt, title="My Game")
renderer.run()
```

The `.sb3` files produced by `save()` are valid for the Scratch editor.
Each target gets at least one costume with actual PNG data, and all block
inputs, fields, parent links, and variable references conform to the SB3
schema.

## Examples

See `examples/` for runnable projects:

| Example | What it demonstrates |
|---------|---------------------|
| `bouncing_ball.py` | Basic hat + forever + move + bounce |
| `key_mover.py` | Multiple hats, key events, variables, reporter nesting |
| `cat_chase_mouse.py` | Two sprites, `point_towards`, inter-sprite interaction |
| `pen_artist.py` | Pen extension blocks |
| `calculator.py` | Reporter nesting with arithmetic and variable reporters |
| `all_in_one.py` | All categories combined, replicating `vm/demo.py` |
