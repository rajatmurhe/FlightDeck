"""One FlightDeck run (runtime): pre-flight, act, verify, seal.

Gets only a page, the portal URL, an opaque run ID, the confirmed contract, the recorded script
and the request. Every run ends in seal(); a receipt is never written any other way.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Page

from flightdeck.contract import requested_lines, short
from flightdeck.executor import replay_a0
from flightdeck.receipt_rules import CHANGE_CLAIM, compute_verdict, seal
from flightdeck.verifier import Evidence, preflight, verify

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_SCHEMA = ROOT / "schemas" / "verifier-receipt.schema.json"
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_TIMEOUT_MS = 5000
ARMS = {"A0": "A0_naive"}


def _unknown(contract: dict, pre, target: str) -> list[str]:
    ch = contract["change"][0]
    hits = ", ".join(sorted(set(pre.resolved_ids) - {target})) or "none besides the target"
    who = pre.clinician or "the clinician"
    items = [f"Records outside scope: only {target}, recorded-locator hits ({hits}), and {who}'s "
             f"{short(ch['to'])} and {short(ch['from'])} slots were checked",
             "How many writes the portal performed: no history view exists"]
    items += [f"{i['effect']}: not shown in the UI" for i in contract.get("incidental", [])
              if not i["visible_in_ui"]]
    return items


def _summary(target: str, verdict: str, wrote: bool, v: dict, message: str | None, error: str | None) -> str:
    obs_start = v["target_observed"].get("start")
    if verdict == "verified_within_scope":
        what = "now shows the requested start" if wrote else "is unchanged"
        s = (f"{target} {what} ({short(obs_start)}) after {v['target_reads']} fresh read(s); preserved "
             "fields match, both slots match the claim, and no at-risk record changed.")
    elif verdict == "observed_mismatch":
        if v["target_result"] == "fail" and obs_start:
            s = (f"Requested {'move failed' if wrote else 'no-change not confirmed'}. {target} shows "
                 f"{short(obs_start)} after {v['target_reads']} fresh reads over {v['poll_seconds']} s")
            s += f", although the portal said '{message}'." if message else "."
        else:
            s = f"Mismatch in scope for {target}."
        if v["affected"]:
            s += " Changed instead: " + "; ".join(f"{a['id']} ({a['change_observed']})" for a in v["affected"]) + "."
        if wrote:
            s += " No retry was made."
    else:
        s = f"Could not confirm {target}: a required field or view was unreadable after {v['target_reads']} read(s)."
    if error and not wrote:
        s = f"Stopped before any write ({error[:80]}). " + s
    return s[:400]


def run_case(page: Page, base_url: str, run_id: str, contract: dict, script: dict, request: dict,
             runs_dir: str | Path, arm: str = "A0") -> dict:
    if arm not in ARMS:
        raise ValueError(f"arm {arm!r} not built yet")
    t0 = time.monotonic()
    base = base_url.rstrip("/")
    hexid = run_id.removeprefix("run-")
    ev = Evidence(Path(runs_dir) / hexid)
    page.set_default_timeout(DEFAULT_TIMEOUT_MS)
    target = contract["target"]["id"]

    pre = preflight(page, base, contract, script, ev)
    action = replay_a0(page, base, script, request)
    wrote = action["writes_submitted"] == 1
    v = verify(page, base, contract, pre, wrote, ev)
    verdict = compute_verdict(v["checks"])

    receipt = {
        "receipt_id": f"rcpt-{hexid}",
        "run_id": run_id,
        "contract_id": contract["contract_id"],
        "arm": ARMS[arm],
        "requested": requested_lines(contract, request["clinician"]),
        "action": {"outcome": "write_submitted" if wrote else "stopped_before_write",
                   "writes_submitted": action["writes_submitted"],
                   "portal_message": action["portal_message"],
                   "guard_events": [], "repair": None},
        "claim": CHANGE_CLAIM if wrote else "no_change",
        "checks": v["checks"],
        "affected_records": [] if verdict == "verified_within_scope" else v["affected"],
        "verdict": verdict,
        "unknown": _unknown(contract, pre, target),
        "summary": _summary(target, verdict, wrote, v, action["portal_message"], action["error"]),
        "runtime_ms": int((time.monotonic() - t0) * 1000),
        "sealed_at": datetime.now(IST).isoformat(timespec="seconds"),
    }
    runs_log = Path(runs_dir) / "runs.log"
    digest = seal(contract, receipt, json.loads(RECEIPT_SCHEMA.read_text()), str(runs_log))
    receipt_path = ev.dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return {"receipt": receipt, "digest": digest, "receipt_path": receipt_path,
            "write_at": action["write_at"]}
