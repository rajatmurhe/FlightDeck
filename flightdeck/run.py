"""One FlightDeck run (runtime): pre-flight, pre-write checks (A1), act, verify, seal.

Gets only a page, the portal URL, an opaque run ID, the confirmed contract, the recorded script
and the request. Every run ends in seal(); a receipt is never written any other way.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Page

from flightdeck.checks import Decision, prewrite
from flightdeck.contract import requested_lines, short
from flightdeck.executor import replay
from flightdeck.receipt_rules import CHANGE_CLAIM, compute_verdict, seal
from flightdeck.verifier import Evidence, preflight, verify

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_SCHEMA = ROOT / "schemas" / "verifier-receipt.schema.json"
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_TIMEOUT_MS = 5000
ARMS = {"A0": "A0_naive", "A1": "A1_rules"}


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


def _why_no_write(decision: Decision | None, guard_events: list[dict], target: str, error: str | None) -> str:
    if decision and decision.then == "refuse_no_change":
        return f"Refused. {decision.reason}, and the contract says to change nothing when that slot is taken."
    if decision:
        return f"Stopped before any write: {decision.reason}; the contract says to stop and ask."
    if guard_events:
        g = guard_events[0]
        return (f"Stopped before any write: the recorded row showed {g['displayed_id']} instead of {target}, "
                "so the guard blocked the click.")
    return f"Stopped before any write ({(error or 'the recorded step could not run')[:80]})."


def _summary(target: str, verdict: str, wrote: bool, v: dict, message: str | None, why: str) -> str:
    obs = v["target_observed"]
    dest = next(c for c in v["checks"] if c["check"] == "destination_slot")
    parts = [why] if why else []
    if verdict == "verified_within_scope":
        if wrote:
            parts.append(f"{target} now shows the requested start ({short(obs['start'])}) after "
                         f"{v['target_reads']} fresh read(s); preserved fields match, both slots match "
                         "the claim, and no at-risk record changed.")
        else:
            parts.append(f"{target} is still {short(obs['start'])}, both slots are unchanged, and no "
                         "at-risk record changed. No write was submitted.")
    elif verdict == "observed_mismatch":
        if v["target_result"] == "fail" and obs.get("start"):
            s = (f"Requested {'move failed' if wrote else 'no-change not confirmed'}. {target} shows "
                 f"{short(obs['start'])} after {v['target_reads']} fresh reads over {v['poll_seconds']} s")
            parts.append(s + (f", although the portal said '{message}'." if message else "."))
        elif dest["result"] == "fail" and dest["observed"].get("occupants"):
            parts.append(f"{target} moved, but {dest['subject']} now holds "
                         f"{', '.join(dest['observed']['occupants'])} (double booking).")
        else:
            parts.append(f"A check in scope failed for {target}.")
        if v["affected"]:
            parts.append("Changed instead: " + "; ".join(f"{a['id']} ({a['change_observed']})"
                                                        for a in v["affected"]) + ".")
        if wrote:
            parts.append("No retry was made.")
    else:
        missing = [f for f in ("start", "clinician", "patient", "duration_min", "status") if f not in obs]
        parts.append(f"Could not confirm {target}: the detail page does not show "
                     f"{', '.join(missing) or 'every required field'} after {v['target_reads']} read(s).")
    return " ".join(parts)[:400]


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

    pre = preflight(page, base, contract, script, ev, clinician_hint=request["clinician"])
    decision = prewrite(contract, pre) if arm != "A0" else None   # A0 runs no checks
    if decision:
        action = {"writes_submitted": 0, "write_at": None, "portal_message": None, "error": None,
                  "guard_events": []}
    else:
        action = replay(page, base, script, request, guard=(arm != "A0"))
    wrote = action["writes_submitted"] == 1
    v = verify(page, base, contract, pre, wrote, ev)
    verdict = compute_verdict(v["checks"])
    if wrote:
        outcome = "write_submitted"
    elif decision:
        outcome = decision.outcome
    else:
        outcome = "stopped_before_write"
    why = "" if wrote else _why_no_write(decision, action["guard_events"], target, action["error"])

    receipt = {
        "receipt_id": f"rcpt-{hexid}",
        "run_id": run_id,
        "contract_id": contract["contract_id"],
        "arm": ARMS[arm],
        "requested": requested_lines(contract, request["clinician"]),
        "action": {"outcome": outcome,
                   "writes_submitted": action["writes_submitted"],
                   "portal_message": action["portal_message"],
                   "guard_events": action["guard_events"], "repair": None},
        "claim": CHANGE_CLAIM if wrote else "no_change",
        "checks": v["checks"],
        "affected_records": [] if verdict == "verified_within_scope" else v["affected"],
        "verdict": verdict,
        "unknown": _unknown(contract, pre, target),
        "summary": _summary(target, verdict, wrote, v, action["portal_message"], why),
        "runtime_ms": int((time.monotonic() - t0) * 1000),
        "sealed_at": datetime.now(IST).isoformat(timespec="seconds"),
    }
    runs_log = Path(runs_dir) / "runs.log"
    digest = seal(contract, receipt, json.loads(RECEIPT_SCHEMA.read_text()), str(runs_log))
    receipt_path = ev.dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return {"receipt": receipt, "digest": digest, "receipt_path": receipt_path,
            "write_at": action["write_at"]}
