"""
Data opcodes — variable and list operations.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import Runtime
    from ..target import Target
    from ..types import Block

from . import (
    _field_val,
    _num,
    _scratch_compare,
    _to_list_index,
    LIST_ITEM_LIMIT,
)


# ═════════════════════════════════════════════════════════════════════════
#  Variables
# ═════════════════════════════════════════════════════════════════════════


def data_setvariableto(rt: Runtime, tgt: Target, block: Block) -> None:
    var_name = _field_val(block.fields.get('VARIABLE'))
    value = rt.val(tgt, block, 'VALUE')
    if var_name:
        var = tgt.lookup_variable(var_name)
        if var is None and rt.stage:
            var = rt.stage.lookup_variable(var_name)
        if var:
            var.value = value
            if var.is_cloud:
                rt.io_query('cloud', 'request_update_variable', var.name, value)


def data_changevariableby(rt: Runtime, tgt: Target, block: Block) -> None:
    var_name = _field_val(block.fields.get('VARIABLE'))
    delta = rt.num(tgt, block, 'VALUE')
    if var_name:
        var = tgt.lookup_variable(var_name)
        if var is None and rt.stage:
            var = rt.stage.lookup_variable(var_name)
        if var:
            var.value = _num(var.value) + delta
            if var.is_cloud:
                rt.io_query('cloud', 'request_update_variable', var.name, var.value)


def data_showvariable(rt: Runtime, tgt: Target, block: Block) -> None:
    """Toggle variable monitor visibility — no-op for now."""


def data_hidevariable(rt: Runtime, tgt: Target, block: Block) -> None:
    """Toggle variable monitor visibility — no-op for now."""


def data_variable(rt: Runtime, tgt: Target, block: Block) -> Any:
    var_name = _field_val(block.fields.get('VARIABLE'))
    if var_name:
        var = tgt.lookup_variable(var_name)
        if var is None and rt.stage:
            var = rt.stage.lookup_variable(var_name)
        if var:
            return var.value
    return 0


# ═════════════════════════════════════════════════════════════════════════
#  Lists
# ═════════════════════════════════════════════════════════════════════════


def data_addtolist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.val(tgt, block, 'ITEM')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst and len(lst.contents) < LIST_ITEM_LIMIT:
            lst.contents.append(item)


def data_deleteoflist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    value = rt.val(tgt, block, 'INDEX')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            idx = _to_list_index(value, len(lst.contents))
            if idx == 'ALL':
                lst.contents.clear()
            elif isinstance(idx, int):
                del lst.contents[idx - 1]


def data_insertatlist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.val(tgt, block, 'ITEM')
    idx_val = rt.val(tgt, block, 'INDEX')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            length = len(lst.contents)
            if length >= LIST_ITEM_LIMIT:
                lst.contents.pop()
                length = len(lst.contents)
            if isinstance(idx_val, str):
                v = idx_val.lower()
                if v == 'last':
                    pos = length
                elif v in ('random', 'any'):
                    pos = random.randint(0, length)
                else:
                    idx = _to_list_index(idx_val, length)
                    if isinstance(idx, int):
                        pos = min(idx - 1, length)
                    else:
                        return
            else:
                idx = _to_list_index(idx_val, length)
                if isinstance(idx, int):
                    pos = min(idx - 1, length)
                else:
                    return

            lst.contents.insert(max(0, pos), item)


def data_replaceitemoflist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.val(tgt, block, 'ITEM')
    value = rt.val(tgt, block, 'INDEX')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            idx = _to_list_index(value, len(lst.contents))
            if isinstance(idx, int):
                lst.contents[idx - 1] = item


def data_deletealloflist(rt: Runtime, tgt: Target, block: Block) -> None:
    list_name = _field_val(block.fields.get('LIST'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            lst.contents.clear()


def data_itemoflist(rt: Runtime, tgt: Target, block: Block) -> Any:
    list_name = _field_val(block.fields.get('LIST'))
    value = rt.val(tgt, block, 'INDEX')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            idx = _to_list_index(value, len(lst.contents))
            if isinstance(idx, int):
                return lst.contents[idx - 1]
    return ''


def data_lengthoflist(rt: Runtime, tgt: Target, block: Block) -> Any:
    list_name = _field_val(block.fields.get('LIST'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            return len(lst.contents)
    return 0


def data_listcontainsitem(rt: Runtime, tgt: Target, block: Block) -> Any:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.val(tgt, block, 'ITEM')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            return any(_scratch_compare(item, x) == 0 for x in lst.contents)
    return False


def data_itemnumoflist(rt: Runtime, tgt: Target, block: Block) -> Any:
    list_name = _field_val(block.fields.get('LIST'))
    item = rt.val(tgt, block, 'ITEM')
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            for i, x in enumerate(lst.contents, 1):
                if _scratch_compare(item, x) == 0:
                    return i
    return 0


def data_listcontents(rt: Runtime, tgt: Target, block: Block) -> Any:
    """Reporter: return list contents as a space-separated string."""
    list_name = _field_val(block.fields.get('LIST'))
    if list_name:
        lst = tgt.lookup_list(list_name)
        if lst is None and rt.stage:
            lst = rt.stage.lookup_list(list_name)
        if lst:
            items = lst.contents
            if all(len(str(x)) == 1 for x in items):
                return ''.join(str(x) for x in items)
            else:
                return ' '.join(str(x) for x in items)
    return ''


def data_hidelist(rt: Runtime, tgt: Target, block: Block) -> None:
    """Hide list monitor — no-op."""


def data_showlist(rt: Runtime, tgt: Target, block: Block) -> None:
    """Show list monitor — no-op."""
