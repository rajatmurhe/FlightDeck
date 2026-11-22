"""Record the reschedule flow once, through the browser only.

Captures what a replayer needs: the target's row position, the button name inside that row,
the ID-cell anchor in the same row (for the A1 guard later), the new-start field, the save
button and the success text. Walking the flow performs one real reschedule on the record-time
portal, so record against a throwaway copy.

It also keeps the demo's visible before/after of the target's detail page, which is what the
contract is drafted from (flightdeck.contract.draft_from_demo).

CLI: python -m flightdeck.record --base-url URL --target A-104 --new-start 2026-12-17T11:00 --out FILE
     (writes FILE and FILE with .demo.json beside it)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from flightdeck.verifier import read_record

ROW_SELECTOR = "table tbody tr"
ANCHOR_SELECTOR = "td.appt-id"
LIST_PATH = "/appointments"


def record(page: Page, base_url: str, target_id: str, new_start: str) -> dict:
    base = base_url.rstrip("/")
    page.goto(base + LIST_PATH)
    rows = page.locator(ROW_SELECTOR)
    ids = [rows.nth(i).locator(ANCHOR_SELECTOR).inner_text().strip() for i in range(rows.count())]
    if ids.count(target_id) != 1:
        raise RuntimeError(f"expected exactly one row showing {target_id}, saw {ids}")
    index = ids.index(target_id)
    row = rows.nth(index)

    buttons = row.get_by_role("button")
    if buttons.count() != 1:
        raise RuntimeError("expected exactly one button in the target row")
    row_button = buttons.first.inner_text().strip()
    buttons.first.click()

    field = page.locator("input[type=datetime-local]")
    field_selector = "#" + field.get_attribute("id")
    field.fill(new_start)
    save = page.locator("form").filter(has=field).get_by_role("button")
    save_name = save.inner_text().strip()
    save.click()
    page.wait_for_load_state()
    success_text = page.get_by_role("status").inner_text().strip()

    return {
        "script_version": "0.1",
        "steps": [
            {"action": "goto", "path": LIST_PATH},
            {"action": "click", "row": {"selector": ROW_SELECTOR, "index": index},
             "role": "button", "name": row_button,
             "anchor": {"selector": ANCHOR_SELECTOR, "value": target_id}},
            {"action": "fill", "selector": field_selector, "value": "{to}"},
            {"action": "click", "role": "button", "name": save_name, "submits_write": True},
            {"action": "expect_text", "text": success_text},
        ],
    }


def record_with_demo(page: Page, base_url: str, target_id: str, new_start: str) -> tuple[dict, dict]:
    base = base_url.rstrip("/")
    before = read_record(page, base, target_id)
    script = record(page, base, target_id, new_start)
    after = read_record(page, base, target_id)
    demo = {"target_id": target_id, "before": before["fields"], "after": after["fields"]}
    return script, demo


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m flightdeck.record")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--new-start", required=True, help="YYYY-MM-DDTHH:MM used for the walk-through")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        script, demo = record_with_demo(browser.new_page(), args.base_url, args.target, args.new_start)
        browser.close()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(script, indent=2) + "\n")
    demo_path = out.with_suffix(".demo.json")
    demo_path.write_text(json.dumps(demo, indent=2) + "\n")
    print(f"recorded {len(script['steps'])} steps -> {out}; demo -> {demo_path}")


if __name__ == "__main__":
    main()
