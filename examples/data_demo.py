#!/usr/bin/env python3
"""Data model demo — variables, lists, operators, and loop counters.

Demonstrates all Scratch data types (int, float, str, bool), every list
operation (insert, get, replace, delete, length, contains), cross-type
comparison semantics, and repeat-loop counters.  Costumes are rendered
programmatically from pygame Surfaces so no external assets are needed.

Usage::

    uv run python examples/data_demo.py
"""

from __future__ import annotations

from pathlib import Path

import pygame

from scratch.dsl import Project, control, data, looks, operators

# ── Costume builders (pygame Surfaces → PNG bytes) ─────────────────────


def _circle_surface(r: int, color: tuple[int, ...]) -> pygame.Surface:
    surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
    pygame.draw.circle(surf, color, (r, r), r)
    pygame.draw.circle(surf, (0, 0, 0), (r, r), r, 2)
    return surf


# ── Project ────────────────────────────────────────────────────────────

project = Project("Data Model Demo", assets_dir=Path(__file__).parent)

# Stage backdrop
project.stage.costume(
    "Stage",
    data=_circle_surface(240, (200, 220, 255)),
    rotation_center_x=240,
    rotation_center_y=180,
)

# ═══════════════════════════════════════════════════════════════════════
#  Sprite 1: Type Tester — variable types & coercion
# ═══════════════════════════════════════════════════════════════════════
s = project.sprite("TypeTester")
s.costume("dot", data=_circle_surface(30, (255, 100, 100)))
s.var("intVar", 0)
s.var("floatVar", 0.0)
s.var("strVar", "")
s.var("result", "")

s.when_flag_clicked(
    data.set_variable("intVar", 42),
    looks.say(operators.join("int = ", data.variable("intVar"))),
    control.wait(1),
    data.set_variable("floatVar", 3.14),
    looks.say(operators.join("float = ", data.variable("floatVar"))),
    control.wait(1),
    data.set_variable("strVar", "hello"),
    looks.say(operators.join("str = ", data.variable("strVar"))),
    control.wait(1),
    data.set_variable("result", True),
    looks.say(operators.join("bool = ", data.variable("result"))),
    control.wait(1),
    data.set_variable("intVar", 10),
    data.set_variable("floatVar", 2.5),
    data.set_variable(
        "result",
        operators.add(data.variable("intVar"), data.variable("floatVar")),
    ),
    looks.say(operators.join("10 + 2.5 = ", data.variable("result"))),
    control.wait(1.5),
    looks.say('123 == "123" → True'),
    control.wait(1.5),
)

# ═══════════════════════════════════════════════════════════════════════
#  Sprite 2: List Operator — all list operations
# ═══════════════════════════════════════════════════════════════════════
s = project.sprite("ListOps")
s.costume("dot", data=_circle_surface(30, (100, 200, 100)))
s.list_("myList", ["apple", "banana", "cherry"])

s.when_flag_clicked(
    looks.say("List: apple, banana, cherry"),
    control.wait(1.0),
    data.insert_at_list("myList", "blueberry", 2),
    looks.say(operators.join("after insert 2: ", data.list_contents("myList"))),
    control.wait(1.5),
    data.insert_at_list("myList", "date", "last"),
    looks.say(operators.join("after insert last: ", data.list_contents("myList"))),
    control.wait(1.5),
    looks.say(operators.join("item 3 = ", data.item_of_list("myList", 3))),
    control.wait(1.0),
    looks.say(operators.join("last = ", data.item_of_list("myList", "last"))),
    control.wait(1.0),
    data.replace_item_of_list("myList", 2, "blackberry"),
    looks.say(operators.join("replace 2: ", data.list_contents("myList"))),
    control.wait(1.5),
    data.delete_of_list("myList", "last"),
    looks.say(operators.join("delete last: ", data.list_contents("myList"))),
    control.wait(1.5),
    looks.say(operators.join("length = ", data.length_of_list("myList"))),
    control.wait(1.0),
    data.delete_all_of_list("myList"),
    looks.say(operators.join("cleared, len = ", data.length_of_list("myList"))),
    control.wait(1.5),
)

# ═══════════════════════════════════════════════════════════════════════
#  Sprite 3: Comparator — cross-type comparison semantics
# ═══════════════════════════════════════════════════════════════════════
s = project.sprite("Comparator")
s.costume("dot", data=_circle_surface(30, (100, 100, 255)))
s.var("result", 0)

s.when_flag_clicked(
    looks.say("5 > 3 → True"),
    control.wait(1.0),
    looks.say('123 == "123" → True'),
    control.wait(1.0),
    looks.say('"abc" == "ABC" → True'),
    control.wait(1.0),
    looks.say('"hello" < 5 → False (str > num)'),
    control.wait(1.5),
    looks.say('"" vs 0 → different (NaN path)'),
    control.wait(1.5),
    data.set_variable("result", operators.div(1, 0)),
    looks.say(operators.join("1/0 = ", data.variable("result"))),
    control.wait(1.5),
    looks.say("Done!"),
)

# ═══════════════════════════════════════════════════════════════════════
#  Sprite 4: Loop Counter — repeat loop with counter
# ═══════════════════════════════════════════════════════════════════════
s = project.sprite("LoopCounter")
s.costume("dot", data=_circle_surface(30, (255, 200, 50)))
s.var("i", 0)
s.var("sum", 0)

s.when_flag_clicked(
    data.set_variable("sum", 0),
    looks.say("Sum 1 to 5:"),
    control.wait(0.5),
    data.set_variable("i", 1),
    control.repeat(5)(
        data.change_variable("sum", data.variable("i")),
        data.change_variable("i", 1),
    ),
    looks.say(operators.join("sum(1..5) = ", data.variable("sum"))),
    control.wait(2.0),
    looks.say("All demos done!"),
)


# ═════════════════════════════════════════════════════════════════════════
#  Main
# ═════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", "-o", type=str, help="Save project to .sb3 file")
    args = parser.parse_args()

    if args.save:
        project.save(args.save)
        print(f"Saved to {args.save}")
    else:
        rt = project.build_runtime()
        from scratch.vm.renderer import Renderer

        renderer = Renderer(rt, title=project.name)
        renderer.run()
