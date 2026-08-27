"""Fixed budget groups and legacy category mapping helpers."""

from __future__ import annotations

from typing import Literal

GROUP_INCOME = "Income"
GROUP_FIXED = "Fixed Expense"
GROUP_VARIABLE = "Variable Expense"
GROUP_DEBT = "Debt"
GROUP_SAVINGS = "Savings"
GROUP_INVESTMENT = "Investment"

BUDGET_GROUPS = (
    GROUP_INCOME,
    GROUP_FIXED,
    GROUP_VARIABLE,
    GROUP_DEBT,
    GROUP_SAVINGS,
    GROUP_INVESTMENT,
)

BudgetGroup = Literal[
    "Income",
    "Fixed Expense",
    "Variable Expense",
    "Debt",
    "Savings",
    "Investment",
]

DIRECTION_INFLOW = "inflow"
DIRECTION_OUTFLOW = "outflow"

GROUP_DIRECTIONS: dict[str, str] = {
    GROUP_INCOME: DIRECTION_INFLOW,
    GROUP_FIXED: DIRECTION_OUTFLOW,
    GROUP_VARIABLE: DIRECTION_OUTFLOW,
    GROUP_DEBT: DIRECTION_OUTFLOW,
    GROUP_SAVINGS: DIRECTION_OUTFLOW,
    GROUP_INVESTMENT: DIRECTION_OUTFLOW,
}

OUTFLOW_GROUPS = tuple(g for g, d in GROUP_DIRECTIONS.items() if d == DIRECTION_OUTFLOW)
INFLOW_GROUPS = tuple(g for g, d in GROUP_DIRECTIONS.items() if d == DIRECTION_INFLOW)

ROLE_GROCERIES = "groceries"

# Maps the legacy 8 expense categories onto seeded (group, name, role) triples.
LEGACY_CATEGORY_SEED: dict[str, tuple[str, str, str | None]] = {
    "Housing": (GROUP_FIXED, "Housing", None),
    "Utilities": (GROUP_FIXED, "Utilities", None),
    "Childcare": (GROUP_FIXED, "Childcare", None),
    "Shopping": (GROUP_FIXED, "Groceries", ROLE_GROCERIES),
    "Transportation": (GROUP_FIXED, "Transport", None),
    "Dining": (GROUP_VARIABLE, "Dining", None),
    "Health": (GROUP_VARIABLE, "Health", None),
    "Other": (GROUP_VARIABLE, "Other", None),
}

# Stable enum values still used by receipt AI extraction.
LEGACY_EXPENSE_CATEGORIES = tuple(LEGACY_CATEGORY_SEED.keys())


def is_inflow_group(group: str) -> bool:
    return GROUP_DIRECTIONS.get(group) == DIRECTION_INFLOW


def is_outflow_group(group: str) -> bool:
    return GROUP_DIRECTIONS.get(group) == DIRECTION_OUTFLOW
