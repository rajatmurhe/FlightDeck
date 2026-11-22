"""Executors (runtime, browser-only).

replay() runs the recorded script. A0 (naive reference arm) replays it literally: it clicks the
recorded row position, never checks the ID anchor, and submits at most one write. A1 adds the ID
guard: before a row click it reads the row's anchor cell and never clicks a row whose displayed
ID differs from the target. Relocating to the target's row is a repair: it only happens when an
accepted repair is passed in, and then the row is found by its ID cell.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

PORTAL_OFFSET = timedelta(hours=5, minutes=30)
SUCCESS_WAIT_MS = 2000
FIELD_WAIT_MS = 3000
DEFAULT_ANCHOR = "td.appt-id"
CONTROL_ROLES = ("button", "menuitem", "link")
MAX_REPAIR_CLICKS = 2


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


def find_control(scope: Locator | Page, name: str, roles: tuple[str, ...] = CONTROL_ROLES) -> Locator | None:
    """The single visible control with exactly this accessible name, or None."""
    for role in roles:
        loc = scope.get_by_role(role, name=name, exact=True)
        if loc.count() == 1:
            return loc
    return None


def anchored_row(page: Page, step: dict, target_id: str) -> Locator | None:
    """The row whose ID cell shows the target (never a row position)."""
    anchor = step.get("anchor", {}).get("selector", DEFAULT_ANCHOR)
    rows = page.locator(step["row"]["selector"]).filter(
        has=page.locator(anchor, has_text=re.compile(rf"^\s*{re.escape(target_id)}\s*$")))
    return rows if rows.count() == 1 else None


def replay_a0(page: Page, base_url: str, script: dict, request: dict) -> dict:
    return replay(page, base_url, script, request, guard=False)


def replay(page: Page, base_url: str, script: dict, request: dict, guard: bool,
           repair: dict | None = None) -> dict:
    base = base_url.rstrip("/")
    target = request["target_id"]
    steps_run: list[str] = []
    writes = 0
    write_at: float | None = None
    message: str | None = None
    error: str | None = None
    guard_events: list[dict] = []
    failed: dict | None = None   # {"step": n, "reason": "guard" | "control_not_found"}

    try:
        for number, step in enumerate(script["steps"], start=1):
            action = step["action"]
            if action == "goto":
                page.goto(base + step["path"])
            elif action == "click" and "row" in step:
                if repair is not None:
                    row = anchored_row(page, step, target)
                    if row is None:
                        failed = {"step": number, "reason": "control_not_found"}
                        break
                    for name in repair["clicks"][:MAX_REPAIR_CLICKS]:
                        control = find_control(row, name)
                        if control is None:
                            failed = {"step": number, "reason": "control_not_found"}
                            break
                        control.click()
                    if failed:
                        break
                else:   # positional: whatever row sits at the recorded index
                    row = page.locator(step["row"]["selector"]).nth(step["row"]["index"])
                    if guard:
                        anchor = row.locator(step.get("anchor", {}).get("selector", DEFAULT_ANCHOR))
                        shown = anchor.inner_text().strip() if anchor.count() == 1 else None
                        if shown != target:
                            guard_events.append({"step": number, "expected_id": target,
                                                 "displayed_id": shown, "action": "blocked_click"})
                            failed = {"step": number, "reason": "guard"}
                            break   # never click it
                    control = find_control(row, step["name"], (step["role"],))
                    if control is None:
                        failed = {"step": number, "reason": "control_not_found"}
                        break
                    control.click()
            elif action == "click":
                control = find_control(page, step["name"], (step["role"],))
                if control is None:
                    error = f"step {number}: no control named {step['name']!r}"
                    break
                if step.get("submits_write"):
                    if writes:
                        raise OneWriteViolation("a second submit was attempted")
                    control.click()
                    writes, write_at = 1, time.monotonic()
                    page.wait_for_load_state()
                else:
                    control.click()
            elif action == "fill":
                field = page.locator(step["selector"])
                try:   # the previous click may still be navigating
                    field.wait_for(timeout=FIELD_WAIT_MS)
                except PlaywrightTimeout:
                    error = f"step {number}: no field {step['selector']!r}"
                    break
                field.fill(_value(step["value"], request))
            elif action == "expect_text":
                try:
                    page.get_by_text(step["text"], exact=True).wait_for(timeout=SUCCESS_WAIT_MS)
                    message = step["text"]
                except PlaywrightTimeout:
                    message = None
            else:
                raise ValueError(f"unknown step action {action!r}")
            steps_run.append(action)
    except PlaywrightError as exc:   # a broken page ends the run; never retried
        error = str(exc).splitlines()[0]

    if failed and error is None:
        error = f"step {failed['step']}: {failed['reason']}"
    return {"steps_run": steps_run, "writes_submitted": writes, "write_at": write_at,
            "portal_message": message, "success_text_seen": message is not None,
            "error": error, "guard_events": guard_events, "failed_row_step": failed,
            "final_url": page.url}
