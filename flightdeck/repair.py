"""Sandbox trial rule (runtime).

A candidate repair is accepted only if, on a fresh sandbox copy, the whole flow with that repair
submits exactly one write and the UI verifier then returns verified_within_scope. The database and
the scorer are never consulted.
"""
from __future__ import annotations

from pathlib import Path

from flightdeck.checks import prewrite
from flightdeck.contract import contract_for
from flightdeck.executor import replay
from flightdeck.receipt_rules import compute_verdict
from flightdeck.sandbox import OpenSandbox
from flightdeck.verifier import Evidence, preflight, verify


def trial(candidate: dict, open_sandbox: OpenSandbox, contract: dict, script: dict, run_dir: Path,
          number: int, allow_new_submits: bool = False) -> dict:
    ev = Evidence(Path(run_dir) / f"trial-{number}")
    with open_sandbox() as sb:
        c = contract_for(contract, sb.request)   # same confirmed lines, fresh inputs
        pre = preflight(sb.page, sb.base_url, c, script, ev, clinician_hint=sb.request["clinician"])
        if prewrite(c, pre):
            return {"accepted": False, "why": "a pre-write check fired in the sandbox"}
        act = replay(sb.page, sb.base_url, script, sb.request, guard=True, repair=candidate,
                     allow_new_submits=allow_new_submits)
        wrote = act["writes_submitted"] == 1
        # Verify either way: a candidate that never reached Save can still have damaged the sandbox.
        v = verify(sb.page, sb.base_url, c, pre, wrote, ev)
        verdict = compute_verdict(v["checks"])
        if not wrote:
            damage = "" if verdict == "verified_within_scope" else f"; sandbox now {verdict}: {_diffs(v)}"
            return {"accepted": False, "why": f"no write in the sandbox ({act['error']}){damage}",
                    "sandbox_verdict": verdict}
        return {"accepted": verdict == "verified_within_scope", "why": f"sandbox verdict {verdict}",
                "sandbox_verdict": verdict}


def _diffs(v: dict) -> str:
    target = next(c for c in v["checks"] if c["check"] == "target")
    diffs = [f"{f} {target['expected'].get(f)} -> {target['observed'][f]}" for f in target["observed"]
             if target["observed"][f] != target["expected"].get(f)]
    return ", ".join(diffs) or "a check failed"
