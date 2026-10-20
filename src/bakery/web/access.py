"""The access matrix: which role may open which area of the site. The only place it lives.

A page joins an area by being registered in `bakery.web.app` with
`dependencies=[requires(Area.X)]`; the nav shows only the areas the account may open.
"""

from __future__ import annotations

from enum import StrEnum

from bakery.models import Account, Role


class Area(StrEnum):
    MASTER_LIST = "master_list"  # 總表
    KITCHEN_SUMMARY = "kitchen_summary"  # 廚房彙總
    OPERATIONS = "operations"  # 上傳紀錄, 模擬群組上傳, 待處理, 品項 and 門市綁定 upkeep
    CUSTOMERS = "customers"  # 客人資料
    # 總部人員's own decisions: confirming 門市綁定. The 老闆 sees them but doesn't make them.
    CONFIRMATIONS = "confirmations"
    HISTORY_IMPORT = "history_import"  # 歷史資料匯入: a one-off onboarding step a 總部人員 runs


_EVERYONE = frozenset(Role)
_HQ_AND_OWNER = frozenset({Role.HQ, Role.OWNER})

ACCESS: dict[Area, frozenset[Role]] = {
    Area.MASTER_LIST: _EVERYONE,
    Area.KITCHEN_SUMMARY: _EVERYONE,
    Area.OPERATIONS: _HQ_AND_OWNER,
    Area.CUSTOMERS: _HQ_AND_OWNER,
    Area.CONFIRMATIONS: frozenset({Role.HQ}),
    Area.HISTORY_IMPORT: frozenset({Role.HQ}),
}


def may_open(account: Account | None, area: Area) -> bool:
    return account is not None and account.role in ACCESS[area]
