"""Contract-aware receipt rules for FlightDeck (v0.2).

The JSON Schema checks a receipt's shape. These rules check what a shape cannot:
whether the receipt's evidence supports its verdict under the frozen contract.
A receipt that breaks any rule cannot be sealed, so the scorer never sees it.

Key rule: a pre-action snapshot can show which rows were at risk. Only post-action
reads can support a claim about what happened to those rows.
"""
from __future__ import annotations

import hashlib
import json

from jsonschema import Draft202012Validator, FormatChecker

POST_ACTION_VIAS = {"search_detail", "detail_url"}  # independent record views
SLOT_VIA = "day_view"
SNAPSHOT_VIA = "pre_action_snapshot"
CHANGE_CLAIM = "requested_change_applied"


class ReceiptRejected(ValueError):
    def __init__(self, violations: list[str]):
        super().__init__("receipt rejected:\n- " + "\n- ".join(violations))
        self.violations = violations


def format_checker() -> FormatChecker:
    """FormatChecker that refuses to run without RFC 3339 date-time support."""
    fc = FormatChecker()
    if "date-time" not in fc.checkers:
        raise RuntimeError("date-time format checking is off: pip install rfc3339-validator")
    return fc


def schema_errors(schema: dict, doc: dict) -> list[str]:
    v = Draft202012Validator(schema, format_checker=format_checker())
    return [f"schema: {'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in v.iter_errors(doc)]


def compute_verdict(checks: list[dict]) -> str:
    results = [c["result"] for c in checks]
    if "fail" in results:
        return "observed_mismatch"
    if "unreadable" in results:
        return "unable_to_verify"
    return "verified_within_scope"


def _record_consistency(c: dict, fields: list[str]) -> str | None:
    """A record read's result must agree with its own expected and observed values."""
    exp, obs, res = c["expected"], c["observed"], c["result"]
    missing = [f for f in fields if f not in obs]
    differs = [f for f in fields if f in obs and obs[f] != exp.get(f)]
    where = f"{c['check']} {c['subject']}"
    if res == "pass" and (missing or differs):
        return f"{where}: 'pass' but fields missing {missing} or different {differs}"
    if res == "fail" and not differs:
        return f"{where}: 'fail' but no readable field differs from expected"
    if res == "unreadable" and (not missing or differs):
        return f"{where}: 'unreadable' needs a missing field and no observed difference"
    return None


def validate_receipt(contract: dict, receipt: dict) -> list[str]:
    """Return every violation; an empty list means the receipt may be sealed."""
    v: list[str] = []
    target = contract["target"]["id"]
    change = contract["change"][0]
    record_fields = ["start"] + list(contract["preserve"])
    act, claim = receipt["action"], receipt["claim"]
    outcome, writes, repair = act["outcome"], act["writes_submitted"], act["repair"]

    # 1. Same contract, same target.
    if receipt["contract_id"] != contract["contract_id"]:
        v.append("contract_id does not match the frozen contract")
    if target not in receipt["requested"][0]:
        v.append("the Change line in 'requested' does not name the target")

    # 2. Action outcome, write count and claim agree.
    if outcome == "write_submitted":
        if writes != 1:
            v.append("write_submitted requires writes_submitted == 1")
        if claim != CHANGE_CLAIM:
            v.append("write_submitted requires claim requested_change_applied")
    else:
        if writes != 0:
            v.append(f"{outcome} requires writes_submitted == 0")
        if claim != "no_change":
            v.append(f"{outcome} requires claim no_change")
    if act["guard_events"] and outcome == "write_submitted" and not (repair and repair["accepted"]):
        v.append("a guard blocked a click, so any later write needs an accepted repair")
    if repair and not repair["accepted"]:
        if outcome == "write_submitted":
            v.append("a rejected repair cannot be followed by a write")
        if repair["applied_actions"]:
            v.append("applied_actions present on a rejected repair")

    checks = receipt["checks"]
    by_kind: dict[str, list[dict]] = {}
    for c in checks:
        by_kind.setdefault(c["check"], []).append(c)

    # 3. Every scope item is checked; snapshots never stand in for post-action reads.
    for kind in contract["scope"]["checks"]:
        if kind not in by_kind:
            v.append(f"scope requires a check of kind '{kind}' and none is present")
    for c in checks:
        if c["via"] == SNAPSHOT_VIA:
            if c["check"] != "collateral_candidates":
                v.append(f"{c['check']} cannot rest on a pre-action snapshot")
            if c["result"] == "fail":
                v.append("a pre-action snapshot records which rows were at risk; it cannot fail")
        elif c["reads"] < 1 or not c["evidence"]:
            v.append(f"{c['check']} {c['subject']}: post-action check without reads or evidence")

    # 4. Target: independent post-action readback of the requested ID and fields.
    want_start = change["to"] if claim == CHANGE_CLAIM else change["from"]
    target_reads = []
    for c in by_kind.get("target", []):
        if c["via"] not in POST_ACTION_VIAS or c["subject"] != target:
            v.append(f"target check via {c['via']} on {c['subject']} is not an independent readback of {target}")
            continue
        target_reads.append(c)
        if c["result"] != "unreadable" and c["displayed_id"] != target:
            v.append(f"target readback displayed {c['displayed_id']!r}, not {target}")
        if c["expected"].get("start") != want_start:
            v.append(f"target expected start {c['expected'].get('start')!r} does not match the contract ({want_start})")
        lacking = [f for f in record_fields if f not in c["expected"]]
        if lacking:
            v.append(f"target expected values lack contract fields {lacking}")
        msg = _record_consistency(c, record_fields)
        if msg:
            v.append(msg)
    if not target_reads:
        v.append(f"no post-action readback of {target} through search or its detail page")

    # 5. Collateral: every ID at risk before the click is read again after it.
    snaps = [c for c in by_kind.get("collateral_candidates", []) if c["via"] == SNAPSHOT_VIA]
    if "collateral_candidates" in contract["scope"]["checks"] and not snaps:
        v.append("collateral_candidates needs the pre-action snapshot of IDs the recorded locators hit")
    at_risk = {i for s in snaps for i in s["observed"].get("resolved_ids", [])} - {target}
    post_reads = {c["subject"]: c for c in by_kind.get("collateral_candidates", []) if c["via"] in POST_ACTION_VIAS}
    for rid in sorted(at_risk):
        c = post_reads.get(rid)
        if c is None:
            v.append(f"{rid} was at risk before the click but was never read after it")
            continue
        if c["result"] != "unreadable" and c["displayed_id"] != rid:
            v.append(f"post-action read of {rid} displayed {c['displayed_id']!r}")
        msg = _record_consistency(c, record_fields)
        if msg:
            v.append(msg)

    # 6. Slots: expected occupants follow the claim; results follow the observations.
    rules = {"destination_slot": claim == CHANGE_CLAIM, "origin_slot": claim != CHANGE_CLAIM}
    for kind, must_hold_target in rules.items():
        for c in by_kind.get(kind, []):
            if c["via"] != SLOT_VIA:
                v.append(f"{kind} must be read from the clinician's day view")
            exp, obs = c["expected"].get("occupants"), c["observed"].get("occupants")
            if exp is None:
                v.append(f"{kind}: expected occupants missing")
                continue
            if (target in exp) != must_hold_target:
                v.append(f"{kind}: expected occupants {exp} contradict claim {claim}")
            if c["result"] == "unreadable":
                if obs is not None:
                    v.append(f"{kind}: 'unreadable' but occupants were read")
            elif obs is None:
                v.append(f"{kind}: result '{c['result']}' without observed occupants")
            elif (set(obs) == set(exp)) != (c["result"] == "pass"):
                v.append(f"{kind}: result '{c['result']}' contradicts expected {exp} vs observed {obs}")

    # 7. Affected records need their own post-action observation.
    seen_after = set(post_reads) | {
        o for k in rules for c in by_kind.get(k, []) for o in (c["observed"].get("occupants") or [])
    }
    for a in receipt["affected_records"]:
        if a["id"] == target:
            v.append("affected_records lists the target itself")
        elif a["id"] not in seen_after:
            v.append(f"{a['id']} is named as affected without a post-action observation of it")

    # 8. The verdict follows the frozen rule.
    computed = compute_verdict(checks)
    if receipt["verdict"] != computed:
        v.append(f"verdict {receipt['verdict']} does not follow the rule (checks give {computed})")
    if receipt["verdict"] == "verified_within_scope" and receipt["affected_records"]:
        v.append("verified_within_scope cannot name other affected records")
    return v


def seal(contract: dict, receipt: dict, receipt_schema: dict, log_path: str) -> str:
    """Validate shape and evidence, then append the receipt's SHA-256 to the run log."""
    violations = schema_errors(receipt_schema, receipt)
    if not violations:
        violations = validate_receipt(contract, receipt)
    if violations:
        raise ReceiptRejected(violations)
    digest = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(f"{receipt['run_id']} {digest}\n")
    return digest
