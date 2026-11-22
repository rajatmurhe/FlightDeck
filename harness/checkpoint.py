"""Day-5 checkpoint: do the 7 core fixtures behave as frozen on the dev seeds?

Runs each core design under A1 and judges it against harness/labels/labels.json, plus the frozen
fixture checks under A0 (R1: A0 writes the decoy; O1: A0 double-books). If anything fails, week 2
goes to verification instead of the repair loop.

CLI: python -m harness.checkpoint [--seeds 1 2 3]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from harness.judge import fixture_check, in_scope_false_approval, judge, load_labels
from harness.reset import DEFAULT_WORKDIR
from harness.run import run

CORE = ["C0", "R1", "O1", "O2", "I1", "S1", "B1"]
DEV_SEEDS = [1, 2, 3]


def checkpoint(seeds: list[int], workdir: Path, runs_dir: Path, designs: list[str] = CORE) -> list[dict]:
    labels = load_labels()
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for design in designs:
            entry = labels[design]
            for seed in seeds:
                out = run(design, seed, "A1", workdir, runs_dir, browser=browser)
                r = out["receipt"]
                j = judge(entry, out["fixture"], r)
                fa = in_scope_false_approval(out["fixture"], r, out["report"])
                rep = r["action"]["repair"]
                rows.append({"design": design, "seed": seed, "arm": "A1", "run_id": r["run_id"],
                             "outcome": r["action"]["outcome"], "verdict": r["verdict"],
                             "named": [a["id"] for a in r["affected_records"]],
                             "repair": (f"{'accepted' if rep['accepted'] else 'rejected'} "
                                        f"{rep['candidates_tried']}/{rep['sandbox_runs']}") if rep else "-",
                             "false_approval": fa, **j})
                if fa:
                    rows[-1].update(ok=False, why="in-scope false approval")
                if "fixture_check" in entry:
                    a0 = run(design, seed, "A0", workdir, runs_dir, browser=browser)
                    fc = fixture_check(entry, a0["fixture"], a0["report"])
                    rows.append({"design": design, "seed": seed, "arm": "A0 fixture check",
                                 "run_id": a0["receipt"]["run_id"],
                                 "outcome": a0["receipt"]["action"]["outcome"],
                                 "verdict": a0["receipt"]["verdict"],
                                 "named": [x["id"] for x in a0["receipt"]["affected_records"]],
                                 "repair": "-", "false_approval": False,
                                 "ok": fc["ok"], "manual_intervention": False, "why": fc["why"]})
        browser.close()
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m harness.checkpoint")
    ap.add_argument("--seeds", type=int, nargs="+", default=DEV_SEEDS)
    ap.add_argument("--designs", nargs="+", default=CORE)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--runs-dir", default="runs")
    args = ap.parse_args(argv)
    if any(s >= 11 for s in args.seeds):
        sys.exit("the checkpoint uses dev seeds only (eval seeds 11-13 run once, on Day 9)")
    state = Path(args.workdir) if args.workdir else DEFAULT_WORKDIR
    rows = checkpoint(args.seeds, state, Path(args.runs_dir), args.designs)

    print(f"{'design':<7}{'seed':<5}{'arm':<18}{'outcome':<22}{'verdict':<23}{'named':<8}"
          f"{'repair (tried/sandbox)':<24}ok")
    for r in rows:
        flag = "yes" + (" (manual intervention)" if r["manual_intervention"] else "")
        print(f"{r['design']:<7}{r['seed']:<5}{r['arm']:<18}{r['outcome']:<22}{r['verdict']:<23}"
              f"{','.join(r['named']) or '-':<8}{r['repair']:<24}{flag if r['ok'] else 'NO  ' + r['why']}")
    passed = sum(r["ok"] for r in rows)
    fas = sum(r["false_approval"] for r in rows)
    print(f"\n{passed}/{len(rows)} as frozen; in-scope false approvals: {fas}")
    (state / "checkpoint.json").write_text(json.dumps(rows, indent=2) + "\n")
    sys.exit(0 if passed == len(rows) else 1)


if __name__ == "__main__":
    main()
