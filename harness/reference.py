"""Run each fixable fixture's frozen reference action through the UI (evaluator side).

The clicks below transcribe 'reference_action' in harness/labels/labels.json. A reference action
passes when the scorer shows exactly the target's start moved to the requested time. Labels are
frozen, so a failure here is reported, never fixed by editing labels.

CLI: python -m harness.reference [--seed 1]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import Browser, sync_playwright

from harness.fixtures import make_fixture
from harness.judge import load_labels
from harness.mutations import install
from harness.portal.server import running
from harness.reset import DEFAULT_WORKDIR, reset
from harness.score import score

REFERENCE_CLICKS = {           # in the row whose ID cell shows the target
    "R1": ["Reschedule"],
    "K0": ["Reschedule appt"],
    "K1": ["Change time"],
    "K2": ["More", "Reschedule"],
}


def run_reference(design: str, seed: int, browser: Browser, workdir: Path) -> dict:
    fx = make_fixture(design, seed)
    db = reset(design, seed, workdir=workdir)
    req = fx["request"]
    with running(db.live, db.flags) as url:
        ctx = browser.new_context()
        install(ctx, fx)
        page = ctx.new_page()
        page.set_default_timeout(5000)
        page.goto(f"{url}/appointments")
        row = page.locator("tbody tr").filter(
            has=page.locator("td.appt-id", has_text=re.compile(rf"^{re.escape(req['target_id'])}$")))
        for name in REFERENCE_CLICKS[design]:
            row.get_by_role("button", name=name, exact=True).or_(
                row.get_by_role("menuitem", name=name, exact=True)).click()
        page.fill("#new_start", req["to"][:16])
        page.get_by_role("button", name="Save").click()
        page.wait_for_load_state()
        ctx.close()
    report = score(db.pristine, db.live)
    want = [{"id": req["target_id"], "fields": ["start"], "before": {"start": req["from"]},
             "after": {"start": req["to"]}}]
    ok = report["changed_rows"] == want and not report["inserted"] and not report["deleted"]
    return {"design": design, "seed": seed, "ok": ok, "changed": report["changed_rows"]}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m harness.reference")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args(argv)
    fixable = [d for d, e in load_labels().items() if e["label"] == "fixable"]
    workdir = Path(args.workdir) if args.workdir else DEFAULT_WORKDIR / "reference"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        results = [run_reference(d, args.seed, browser, workdir) for d in fixable]
        browser.close()
    for r in results:
        print(f"{r['design']:<4} seed {r['seed']}  {'ok' if r['ok'] else 'FAILED ' + str(r['changed'])}")
    print(f"{sum(r['ok'] for r in results)}/{len(results)} reference actions succeed")
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
