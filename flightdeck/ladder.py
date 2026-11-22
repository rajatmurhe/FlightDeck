"""Deterministic repair ladder (runtime, read-only on the real page).

When the recorded row click cannot run (the guard blocked it, or the control is gone), propose
candidates in the target's row, found by its ID cell, in this fixed order:
  1. ID-anchored row, exact recorded name     (relocation, e.g. reordered rows)
  2. fuzzy name: a visible button whose name contains, or is contained in, the recorded name
  3. the row's only visible button
  4. an accessible menu in the row (aria-haspopup): open it, then the recorded name
Each candidate is at most 2 clicks inside that row, no typing, no new submits. Proposing never
clicks anything; candidates are trialled in a sandbox and accepted only by the UI verifier.
"""
from __future__ import annotations

import difflib
import re

from playwright.sync_api import Page

from flightdeck.executor import anchored_row

BUDGET = 3
MIN_FUZZY_LEN = 4


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", s.lower())).strip()


def _fuzzy(recorded: str, name: str) -> bool:
    a, b = _norm(recorded), _norm(name)
    return min(len(a), len(b)) >= MIN_FUZZY_LEN and (a in b or b in a)


def row_step(script: dict) -> dict:
    return next(s for s in script["steps"] if s["action"] == "click" and "row" in s)


def propose(page: Page, base_url: str, script: dict, request: dict) -> list[dict]:
    step = row_step(script)
    list_path = next(s["path"] for s in script["steps"] if s["action"] == "goto")
    page.goto(base_url.rstrip("/") + list_path)   # fresh view, read only
    row = anchored_row(page, step, request["target_id"])
    if row is None:
        return []
    buttons = row.get_by_role("button")   # accessibility tree: hidden menu items are excluded
    names = [buttons.nth(i).inner_text().strip() for i in range(buttons.count())]
    popups = [buttons.nth(i).get_attribute("aria-haspopup") for i in range(buttons.count())]
    recorded = step["name"]

    out: list[dict] = []

    def add(rung: str, clicks: list[str]) -> None:
        if all(c["clicks"] != clicks for c in out):
            out.append({"rung": rung, "clicks": clicks})

    if recorded in names:
        add("id_anchored_exact", [recorded])
    fuzzy = [n for n in names if n != recorded and _fuzzy(recorded, n)]
    if fuzzy:
        best = max(fuzzy, key=lambda n: difflib.SequenceMatcher(None, _norm(recorded), _norm(n)).ratio())
        add("fuzzy_name", [best])
    if len(names) == 1:
        add("only_button", [names[0]])
    for name, popup in zip(names, popups):
        if popup and popup.lower() in {"menu", "true", "listbox"}:
            add("row_menu", [name, recorded])
    return out[:BUDGET]
