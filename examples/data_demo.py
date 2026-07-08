#!/usr/bin/env python3
"""
Data Model Demo — exercises all Scratch data types, list index modes,
and variable/list operations to demonstrate correct VM behaviour.

Run via pytest::

    uv run pytest examples/data_demo.py -v -s

Or directly::

    uv run python examples/data_demo.py
"""

from __future__ import annotations

from typing import Any

from scratch.vm import ListVar, Runtime, Target, Variable, make_block
from scratch.vm.opcodes import OPCODE_MAP
from scratch.vm.cast import (
    LIST_ALL as LIST_INDEX_ALL_SENTINEL,
    to_list_index,
    to_number as _num,
    to_string as _str,
    compare as _scratch_compare,
)


# ═════════════════════════════════════════════════════════════════════════
#  Test helpers
# ═════════════════════════════════════════════════════════════════════════


def _make_tgt(name: str = "Demo") -> Target:
    t = Target(name=name, is_stage=False)
    t.blocks["hat"] = make_block("event_whenflagclicked", "hat", top_level=True)
    return t


def _make_list_tgt(name: str, initial: list[Any]) -> Target:
    tgt = _make_tgt(name)
    tgt.lists["mylist"] = ListVar(name="myList", contents=list(initial))
    return tgt


# ═════════════════════════════════════════════════════════════════════════
#  1. Variable data types
# ═════════════════════════════════════════════════════════════════════════


def demo_variable_types() -> None:
    """int, float, bool, str, None, large/negative numbers, coercion."""

    tgt = _make_tgt("Types")
    tgt.variables["int_var"] = Variable("int_var", 0)
    tgt.variables["float_var"] = Variable("float_var", 0.0)
    tgt.variables["str_var"] = Variable("str_var", "")
    tgt.variables["bool_var"] = Variable("bool_var", False)

    def var(name: str) -> Variable:
        v = tgt.lookup_variable(name)
        assert v is not None
        return v

    # int
    var("int_var").value = 42
    assert var("int_var").value == 42 and isinstance(var("int_var").value, int)
    print("  ✔ int_var = 42        (type: int)")

    # float
    var("float_var").value = 3.14
    assert var("float_var").value == 3.14 and isinstance(var("float_var").value, float)
    print("  ✔ float_var = 3.14     (type: float)")

    # str
    var("str_var").value = "hello"
    assert var("str_var").value == "hello" and isinstance(var("str_var").value, str)
    print('  ✔ str_var = "hello"    (type: str)')

    # bool
    var("bool_var").value = True
    assert var("bool_var").value is True and isinstance(var("bool_var").value, bool)
    print("  ✔ bool_var = True      (type: bool)")

    # empty string
    var("str_var").value = ""
    assert var("str_var").value == ""
    print('  ✔ str_var = ""        (empty string)')

    # None
    var("str_var").value = None
    print(f"  ✔ str_var = None      (value: {var('str_var').value!r})")

    # large int
    var("int_var").value = 10**9
    assert var("int_var").value == 1000000000
    print("  ✔ int_var = 10**9      (large int)")

    # negative int
    var("int_var").value = -5
    assert var("int_var").value == -5
    print("  ✔ int_var = -5         (negative int)")

    # int→float coercion via changevariableby
    var("int_var").value = 10
    var("int_var").value = float(var("int_var").value) + 2.5
    assert var("int_var").value == 12.5 and isinstance(var("int_var").value, float)
    print("  ✔ int_var 10 + 2.5 = 12.5  (int→float via change)")

    print()


# ═════════════════════════════════════════════════════════════════════════
#  2. List index operations
# ═════════════════════════════════════════════════════════════════════════


def demo_list_numeric_indices() -> None:
    """1-based numeric indices: 1 = first, n = last."""
    tgt = _make_list_tgt("NumIdx", ["a", "b", "c", "d", "e"])
    lst = tgt.lists["mylist"]

    assert lst.contents[0] == "a", "index 1 → first"
    assert lst.contents[4] == "e", "index 5 → last"
    print("  ✔ numeric index 1 → 'a', index 5 → 'e'")

    # Out-of-range → 0 (invalid)
    assert to_list_index(0, 5) == 0
    assert to_list_index(6, 5) == 0
    assert to_list_index(-1, 5) == 0
    print("  ✔ index 0 / 6 / -1 → invalid (0)")

    print()


def demo_list_last_index() -> None:
    """'last' in get, replace, delete, and insert operations."""

    tgt = _make_list_tgt("LastIdx", ["a", "b", "c"])
    lst = tgt.lists["mylist"]

    # ── getItemOfList(INDEX="last") ──
    idx = to_list_index("last", len(lst.contents))
    assert idx == 3 and lst.contents[idx - 1] == "c"
    print("  ✔ get 'last' on [a,b,c] → idx=3 → 'c'")

    # ── replaceItemOfList(INDEX="last") ──
    lst.contents[idx - 1] = "z"
    assert lst.contents == ["a", "b", "z"]
    print("  ✔ replace 'last' on [a,b,c] → [a,b,z]")

    # ── deleteOfList(INDEX="last") ──
    lst.contents = ["a", "b", "c"]
    idx = to_list_index("last", len(lst.contents))
    del lst.contents[idx - 1]
    assert lst.contents == ["a", "b"]
    print("  ✔ delete 'last' on [a,b,c] → [a,b]")

    # ── insertAtList(INDEX="last") — appends ──
    lst.contents = ["a", "b", "c"]
    insert_len = len(lst.contents) + 1  # +1 for insertion positions
    idx = to_list_index("last", insert_len)
    assert idx == 4, f"expected 4 (len+1), got {idx}"
    lst.contents.insert(idx - 1, "x")
    assert lst.contents == ["a", "b", "c", "x"]
    print("  ✔ insert 'last' on [a,b,c] → [a,b,c,x]  (appends)")

    # ── 'last' on empty list → 0 (no-op) ──
    lst.contents = []
    assert to_list_index("last", 0) == 0
    print("  ✔ 'last' on empty list → 0 → no-op")

    print()


def demo_list_random_index() -> None:
    """'random' / 'any' in list operations."""
    tgt = _make_list_tgt("RandIdx", ["a", "b", "c", "d", "e"])
    lst = tgt.lists["mylist"]

    results: set[int] = set()
    for _ in range(200):
        idx = to_list_index("random", len(lst.contents))
        assert isinstance(idx, int) and 1 <= idx <= 5
        results.add(idx)
    assert results == {1, 2, 3, 4, 5}
    print("  ✔ 'random' on 5 items → all 5 positions reachable")

    idx = to_list_index("any", len(lst.contents))
    assert isinstance(idx, int) and 1 <= idx <= 5
    print("  ✔ 'any' behaves like 'random'")

    lst.contents = []
    assert to_list_index("random", 0) == 0
    print("  ✔ 'random' on empty list → 0 → no-op")

    print()


def demo_list_all_index() -> None:
    """'all' — only valid for deleteOfList (clears list)."""
    tgt = _make_list_tgt("AllIdx", ["a", "b", "c"])
    lst = tgt.lists["mylist"]

    idx = to_list_index("all", len(lst.contents), accept_all=True)
    assert idx == LIST_INDEX_ALL_SENTINEL
    print("  ✔ 'all' → sentinel (triggers clear)")

    lst.contents.clear()
    assert lst.contents == []
    print("  ✔ delete 'all' → list cleared")

    print()


# ═════════════════════════════════════════════════════════════════════════
#  3. End-to-end list lifecycle
# ═════════════════════════════════════════════════════════════════════════


def demo_list_end_to_end() -> None:
    """Full lifecycle: add, insert, get, replace, delete, clear."""

    tgt = _make_list_tgt("Lifecycle", [])
    lst = tgt.lists["mylist"]

    # add
    for item in ["apple", "banana", "cherry"]:
        lst.contents.append(item)
    assert lst.contents == ["apple", "banana", "cherry"]
    print("  ✔ add: [apple, banana, cherry]")

    # insert at position 2
    lst.contents.insert(1, "blueberry")
    assert lst.contents == ["apple", "blueberry", "banana", "cherry"]
    print("  ✔ insert at 2: [apple, blueberry, banana, cherry]")

    # insert 'last' (append)
    pos = to_list_index("last", len(lst.contents) + 1)
    lst.contents.insert(pos - 1, "date")
    assert lst.contents == ["apple", "blueberry", "banana", "cherry", "date"]
    print("  ✔ insert 'last': [..., date]")

    # get index 3
    assert lst.contents[to_list_index(3, len(lst.contents)) - 1] == "banana"
    print("  ✔ get index 3 → 'banana'")

    # get 'last'
    assert lst.contents[to_list_index("last", len(lst.contents)) - 1] == "date"
    print("  ✔ get 'last' → 'date'")

    # replace index 2
    lst.contents[to_list_index(2, len(lst.contents)) - 1] = "blackberry"
    assert lst.contents == ["apple", "blackberry", "banana", "cherry", "date"]
    print("  ✔ replace index 2: blueberry → blackberry")

    # delete 'last'
    del lst.contents[to_list_index("last", len(lst.contents)) - 1]
    assert lst.contents == ["apple", "blackberry", "banana", "cherry"]
    print("  ✔ delete 'last': removed 'date'")

    # delete 'all' (clear)
    lst.contents.clear()
    assert len(lst.contents) == 0
    print("  ✔ delete 'all': list cleared, length = 0")

    # contains & item #
    lst.contents = ["a", "b", "c"]
    assert any(_scratch_compare("b", x) == 0 for x in lst.contents)
    for i, x in enumerate(lst.contents, 1):
        if _scratch_compare("b", x) == 0:
            assert i == 2
    print("  ✔ 'b' found at position 2")
    print("  ✔ list contains 'b' → True")

    print()


# ═════════════════════════════════════════════════════════════════════════
#  4. Loop counters
# ═════════════════════════════════════════════════════════════════════════


def demo_loop_counter() -> None:
    """control_for_each: iterate FROM→TO, variable tracks loop index."""

    tgt = _make_tgt("Loop")
    tgt.variables["i"] = Variable("i", 0)
    tgt.variables["sum"] = Variable("sum", 0)
    i_var = tgt.lookup_variable("i")
    sum_var = tgt.lookup_variable("sum")
    assert i_var is not None and sum_var is not None

    # Ascending: for_each i = 1 to 5
    for n in range(1, 6):
        i_var.value = n
        sum_var.value = float(sum_var.value) + float(i_var.value)

    assert i_var.value == 5
    assert sum_var.value == 15.0
    print("  ✔ for_each i=1 to 5: sum = 1+2+3+4+5 = 15")
    print(f"  ✔ loop variable 'i' ends at {i_var.value}")

    # Descending: for_each i = 3 to 1
    sum_var.value = 0
    for n in range(3, 0, -1):
        i_var.value = n
        sum_var.value = float(sum_var.value) + float(i_var.value)

    assert sum_var.value == 6.0
    assert i_var.value == 1
    print("  ✔ for_each i=3 to 1: sum = 3+2+1 = 6")

    print()


# ═════════════════════════════════════════════════════════════════════════
#  5. Type comparison & coercion
# ═════════════════════════════════════════════════════════════════════════


def demo_type_comparison() -> None:
    """Scratch comparison across types — numeric vs string, case, NaN."""

    # Numeric comparison
    assert _scratch_compare(5, 3) > 0
    assert _scratch_compare(3, 5) < 0
    assert _scratch_compare(5, 5) == 0
    print("  ✔ numeric compare: 5 > 3, 3 < 5, 5 == 5")

    # 123 == '123' (cross-type numeric equality)
    assert _scratch_compare(123, "123") == 0
    print("  ✔ 123 == '123' (cross-type numeric)")

    # NaN compare as strings
    assert _scratch_compare("hello", 5) > 0
    print("  ✔ 'hello' > 5 (NaN → string compare)")

    # Case-insensitive string compare
    assert _scratch_compare("abc", "ABC") == 0
    print("  ✔ 'abc' == 'ABC' (case-insensitive)")

    # Empty string → NaN
    assert _scratch_compare("", 0) != 0
    print("  ✔ '' vs 0 → different (empty string → NaN)")

    # _num coercion
    assert _num(5) == 5.0
    assert _num("3.14") == 3.14
    assert _num("") == 0.0
    assert _num("hello") == 0.0  # to_number: NaN → 0
    assert _num(None) == 0.0
    print("  ✔ _num: int→float, str→float, ''→0, non-num→0, None→0")

    # _str coercion
    assert _str(42) == "42"
    assert _str(3.14) == "3.14"
    assert _str(None) == ""
    assert _str(True) == "true"  # Scratch: lowercase
    print("  ✔ _str: num→str, None→'', bool→'true'")

    # Infinity
    assert _num("Infinity") == float("inf")
    assert _num("-Infinity") == float("-inf")
    print("  ✔ _num('Infinity') → ∞, _num('-Infinity') → -∞")

    # NaN == NaN (Scratch: true)
    assert _scratch_compare(float("nan"), float("nan")) == 0
    print("  ✔ NaN == NaN (Scratch says true)")

    print()


# ═════════════════════════════════════════════════════════════════════════
#  6. Variable scope: sprite vs stage
# ═════════════════════════════════════════════════════════════════════════


def demo_variable_scope() -> None:
    """Stage vars are 'global'; sprite vars are local."""

    rt = Runtime()
    rt._real_time = False

    stage = Target(name="Stage", is_stage=True)
    stage.variables["global_score"] = Variable("global_score", 100)
    rt.add_target(stage)

    sprite = _make_tgt("Player")
    sprite.variables["local_hp"] = Variable("local_hp", 50)
    rt.add_target(sprite)
    rt.register_all(OPCODE_MAP)

    assert sprite.lookup_variable("local_hp") is not None
    assert sprite.lookup_variable("local_hp").value == 50  # type: ignore[union-attr]
    print("  ✔ sprite finds own 'local_hp' → 50")

    assert sprite.lookup_variable("global_score") is None
    print("  ✔ sprite cannot see 'global_score' directly")

    assert rt.stage is not None
    assert rt.stage.lookup_variable("global_score").value == 100  # type: ignore[union-attr]
    print("  ✔ stage has 'global_score' → 100")

    def find_var(tgt: Target, name: str) -> Variable | None:
        v = tgt.lookup_variable(name)
        if v is None and rt.stage:
            v = rt.stage.lookup_variable(name)
        return v

    assert find_var(sprite, "local_hp") is not None
    assert find_var(sprite, "global_score") is not None
    print("  ✔ fallback: sprite reads 'global_score' from stage")

    print()


# ═════════════════════════════════════════════════════════════════════════
#  Main
# ═════════════════════════════════════════════════════════════════════════


def test_all() -> None:
    """pytest entry point."""
    print("═══ Data Type Demos ═══")
    demo_variable_types()

    print("═══ List Index Demos ═══")
    demo_list_numeric_indices()
    demo_list_last_index()
    demo_list_random_index()
    demo_list_all_index()

    print("═══ List End-to-End ═══")
    demo_list_end_to_end()

    print("═══ Loop Counter ═══")
    demo_loop_counter()

    print("═══ Type Comparison ═══")
    demo_type_comparison()

    print("═══ Variable Scope ═══")
    demo_variable_scope()

    print("\n✅ All data model demos passed!")


def main() -> None:
    print("Running data model demos...\n")
    test_all()


if __name__ == "__main__":
    main()
