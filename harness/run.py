"""Run one fixture under one arm, then score it (evaluator side).

The harness resets the fixture, mints an opaque run ID, starts the portal with its fault flags,
installs any browser mutation, and hands FlightDeck only a page, the URL, the run ID, the
contract, the recorded script and the request. After the sealed receipt comes back it waits for
the frozen 15 s settle (from the write), then scores.

CLI: python -m harness.run --design R1 --seed 1 --arm A0
"""
from __future__ import annotations

import argparse
import json
import secrets
import time
from contextlib import ExitStack
from pathlib import Path

from playwright.sync_api import Browser, sync_playwright

from flightdeck.contract import contract_for, load_base
from flightdeck.run import run_case
from harness.fixtures import make_fixture
from harness.mutations import install
from harness.portal.server import running
from harness.reset import DEFAULT_WORKDIR, reset
from harness.score import score_run

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "flightdeck" / "recordings" / "reschedule.json"
SETTLE_S = 15.0
REQUEST_KEYS = ("target_id", "from", "to", "clinician")


def new_run_id() -> str:
    return "run-" + secrets.token_hex(4)


def run(design: str, seed: int, arm: str = "A0", workdir: str | Path | None = None,
        runs_dir: str | Path = "runs", settle: float = SETTLE_S, browser: Browser | None = None) -> dict:
    state = Path(workdir) if workdir is not None else DEFAULT_WORKDIR
    runs = Path(runs_dir)
    runs.mkdir(parents=True, exist_ok=True)
    fx = make_fixture(design, seed)
    db = reset(design, seed, workdir=state)

    run_id = new_run_id()
    run_map = state / "run_map.jsonl"
    with run_map.open("a") as fh:   # evaluator-only: FlightDeck never reads this file
        fh.write(json.dumps({"run_id": run_id, "design": design, "seed": seed, "arm": arm}) + "\n")

    request = {k: fx["request"][k] for k in REQUEST_KEYS}
    contract = contract_for(load_base(), request)
    script = json.loads(SCRIPT.read_text())

    with ExitStack() as stack:
        if browser is None:
            browser = stack.enter_context(sync_playwright()).chromium.launch()
        url = stack.enter_context(running(db.live, db.flags))
        ctx = browser.new_context()
        stack.callback(ctx.close)
        install(ctx, fx)
        out = run_case(ctx.new_page(), url, run_id, contract, script, request, runs, arm=arm)
        if out["write_at"] is not None:   # the portal keeps serving during the settle
            time.sleep(max(0.0, settle - (time.monotonic() - out["write_at"])))

    report = score_run(out["receipt_path"], runs / "runs.log", run_map, db.pristine, db.live)
    reports = state / "reports"
    reports.mkdir(exist_ok=True)
    (reports / f"{run_id}.json").write_text(json.dumps(report, indent=2) + "\n")
    return {"report": report, "receipt": out["receipt"], "receipt_path": out["receipt_path"],
            "fixture": fx}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m harness.run")
    ap.add_argument("--design", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--arm", default="A0", choices=["A0"])
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--settle", type=float, default=SETTLE_S)
    args = ap.parse_args(argv)
    out = run(args.design, args.seed, args.arm, args.workdir, args.runs_dir, args.settle)
    r = out["receipt"]
    print(f"receipt  {out['receipt_path']}")
    print(f"verdict  {r['verdict']}   named {[a['id'] for a in r['affected_records']]}")
    print(f"summary  {r['summary']}")
    print("scorer   " + json.dumps(out["report"], indent=2))


if __name__ == "__main__":
    main()
