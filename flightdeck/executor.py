"""Executors (runtime, browser-only).

A0 is the naive reference arm: it replays the recorded script literally. It clicks the
recorded row position, never checks the ID anchor, runs no pre-write checks, and submits at
most one write. It exists to produce the real wrong writes the verifier must catch.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

PORTAL_OFFSET = timedelta(hours=5, minutes=30)
SUCCESS_WAIT_MS = 2000


class OneWriteViolation(RuntimeError):
    pass


def _local_input(iso: str) -> str:
    """RFC 3339 with +05:30 -> the portal's datetime-local value 'YYYY-MM-DDTHH:MM'."""
    dt = datetime.fromisoformat(iso)
    if dt.utcoffset() != PORTAL_OFFSET:
        raise ValueError(f"expected a +05:30 time, got {iso}")
    return dt.strftime("%Y-%m-%dT%H:%M")


def _value(template: str, request: dict) -> str:
    if template == "{to}":
        return _local_input(request["to"])
    return template


def replay_a0(page: Page, base_url: str, script: dict, request: dict) -> dict:
    base = base_url.rstrip("/")
    steps_run: list[str] = []
    writes = 0
    success_seen = False

    for step in script["steps"]:
        action = step["action"]
        if action == "goto":
            page.goto(base + step["path"])
        elif action == "click":
            scope = page
            if "row" in step:   # positional: whatever row sits at the recorded index
                scope = page.locator(step["row"]["selector"]).nth(step["row"]["index"])
            control = scope.get_by_role(step["role"], name=step["name"], exact=True)
            if step.get("submits_write"):
                if writes:
                    raise OneWriteViolation("a second submit was attempted")
                writes += 1
                control.click()
                page.wait_for_load_state()
            else:
                control.click()
        elif action == "fill":
            page.fill(step["selector"], _value(step["value"], request))
        elif action == "expect_text":
            try:
                page.get_by_text(step["text"], exact=True).wait_for(timeout=SUCCESS_WAIT_MS)
                success_seen = True
            except PlaywrightTimeout:
                success_seen = False
        else:
            raise ValueError(f"unknown step action {action!r}")
        steps_run.append(action)

    return {"steps_run": steps_run, "writes_submitted": writes,
            "success_text_seen": success_seen, "final_url": page.url}
