"""Return eligibility engine.

Evaluates return eligibility for each article in an order by running a
priority-ordered list of rules loaded from ``portal/data/return_rules.yaml``.

Rule conditions are simple expressions over three namespaces:
  - ``item.*``              — Article fields
  - ``policy.*``            — Order-level policy fields (return_window_days)
  - ``days_since_delivery`` — integer, computed at evaluation time

Each rule either ``allow``s or ``deny``s the item.  The first matching rule
wins.  If no rule matches the item is denied (fail-safe default).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from portal.types import ArticleEligibility, Order

_RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "return_rules.yaml"


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------

def _load_rules() -> list[dict[str, Any]]:
    with _RULES_PATH.open() as f:
        data = yaml.safe_load(f)
    rules: list[dict[str, Any]] = data["rules"]
    return sorted(rules, key=lambda r: r["priority"], reverse=True)


# ---------------------------------------------------------------------------
# Condition evaluation
#
# Supported syntax (whitespace-normalised):
#   <clause> [AND <clause> ...]
# where each clause is:
#   <lhs> <op> <rhs>
# and lhs / rhs are one of:
#   - dotted name (item.is_digital, policy.return_window_days, days_since_delivery)
#   - integer / float literal
#   - boolean literal  true / false
#   - quoted string literal  "clearance"  or  'clearance'
# and op is one of:  ==  !=  >  >=  <  <=
# ---------------------------------------------------------------------------

_OP_MAP = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}

_CLAUSE_RE = re.compile(
    r"^(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$"
)


def _resolve(token: str, ctx: dict[str, Any]) -> Any:
    token = token.strip()
    if token == "true":
        return True
    if token == "false":
        return False
    # quoted string literal — single or double quotes
    if (token.startswith('"') and token.endswith('"')) or \
       (token.startswith("'") and token.endswith("'")):
        return token[1:-1]
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    # dotted lookup in context
    parts = token.split(".", 1)
    if len(parts) == 2:
        ns, key = parts
        return ctx[ns][key]
    return ctx[token]


def _evaluate_clause(clause: str, ctx: dict[str, Any]) -> bool:
    m = _CLAUSE_RE.match(clause.strip())
    if not m:
        raise ValueError(f"Cannot parse rule clause: {clause!r}")
    lhs_token, op, rhs_token = m.group(1), m.group(2), m.group(3)
    lhs = _resolve(lhs_token, ctx)
    rhs = _resolve(rhs_token, ctx)
    return _OP_MAP[op](lhs, rhs)


def _evaluate_condition(condition: str, ctx: dict[str, Any]) -> bool:
    clauses = re.split(r"\bAND\b", condition)
    return all(_evaluate_clause(c, ctx) for c in clauses)


# ---------------------------------------------------------------------------
# Reason interpolation  {{ variable }}
# ---------------------------------------------------------------------------

_TEMPLATE_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")


def _render_reason(template: str, ctx: dict[str, Any]) -> str:
    def _sub(m: re.Match) -> str:
        try:
            return str(_resolve(m.group(1), ctx))
        except (KeyError, TypeError):
            return m.group(0)
    return _TEMPLATE_RE.sub(_sub, template)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_eligibility(order: Order) -> list[ArticleEligibility]:
    """Evaluate return eligibility for every article in *order*.

    Rules are loaded from ``portal/data/return_rules.yaml`` and evaluated in
    descending priority order.  The first matching rule determines the outcome.
    If no rule matches, the item is denied by default.

    Returns:
        A list of :class:`ArticleEligibility`, one per article in the order.
    """
    rules = _load_rules()
    days_since_delivery = (datetime.now() - order.delivery_date).days

    results: list[ArticleEligibility] = []
    for article in order.articles:
        ctx: dict[str, Any] = {
            "item": {
                "sku": article.sku,
                "quantity": article.quantity,
                "quantity_returned": article.quantity_returned,
                "price": article.price,
                "is_digital": article.is_digital,
                "is_final_sale": article.is_final_sale,
                "category": article.category,
            },
            "policy": {
                "return_window_days": order.return_window_days,
            },
            "days_since_delivery": days_since_delivery,
        }

        matched_rule: str = ""
        returnable: bool = False
        reason: str = "No rule matched — return not permitted"

        for rule in rules:
            if _evaluate_condition(rule["condition"], ctx):
                matched_rule = rule["id"]
                returnable = rule["action"] == "allow"
                reason = _render_reason(rule.get("reason", ""), ctx)
                break

        results.append(
            ArticleEligibility(
                article=article,
                returnable=returnable,
                reason=reason,
                matched_rule=matched_rule,
            )
        )

    return results
