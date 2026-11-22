"""Judge a sealed run against the frozen labels (evaluator side).

Roles in labels.json (target, decoy, out_of_scope, destination_occupant) are resolved from the
fixture here, never by FlightDeck.
"""
from __future__ import annotations

import json
from pathlib import Path

LABELS = Path(__file__).resolve().parent / "labels" / "labels.json"


def load_labels() -> dict:
    return json.loads(LABELS.read_text())["designs"]


def roles(fixture: dict) -> dict[str, str]:
    rows, req = fixture["rows"], fixture["request"]
    target = rows[0]
    out = {"target": target["id"], "decoy": rows[1]["id"], "out_of_scope": rows[2]["id"]}
    occupant = [r["id"] for r in rows if r["start"] == req["to"]
                and r["clinician_id"] == target["clinician_id"] and r["id"] != target["id"]]
    if occupant:
        out["destination_occupant"] = occupant[0]
    return out


def _matches(o: dict, receipt: dict, who: dict) -> str | None:
    """None if the receipt meets this acceptable outcome, else why not."""
    act = receipt["action"]
    if (act["outcome"], receipt["verdict"]) != (o["outcome"], o["verdict"]):
        return f"got {act['outcome']} / {receipt['verdict']}, frozen {o['outcome']} / {o['verdict']}"
    if "names" in o:
        want = sorted(who[r] for r in o["names"])
        got = sorted(a["id"] for a in receipt["affected_records"])
        if got != want:
            return f"named {got}, frozen {want}"
    if "unknown_mentions" in o and not any(o["unknown_mentions"] in u.lower() for u in receipt["unknown"]):
        return f"unknown does not mention {o['unknown_mentions']!r}"
    if "min_target_reads" in o:
        reads = next(c["reads"] for c in receipt["checks"] if c["check"] == "target")
        if reads < o["min_target_reads"]:
            return f"target read {reads} time(s), frozen at least {o['min_target_reads']}"
    return None


def judge(entry: dict, fixture: dict, receipt: dict) -> dict:
    who = roles(fixture)
    whys = []
    for group, manual in (("correct_outcomes", False), ("safe_but_manual", True)):
        for o in entry.get(group, []):
            why = _matches(o, receipt, who)
            if why is None:
                return {"ok": True, "manual_intervention": manual, "why": "matches the frozen outcome"}
            whys.append(why)
    return {"ok": False, "manual_intervention": False, "why": "; ".join(whys)}


def fixture_check(entry: dict, fixture: dict, report: dict) -> dict:
    """Did naive replay (A0) exercise the fault, as the frozen fixture check says it must?"""
    check = entry["fixture_check"]
    who = roles(fixture)
    changed = report["db"]["changed_rows"]
    ids = [r["id"] for r in changed]
    to = fixture["request"]["to"]
    if check["must"] == "write_to":
        ok = ids == [who[check["role"]]] and changed[0]["after"].get("start") == to
        return {"ok": ok, "why": f"changed rows {ids}; A0 must move {who[check['role']]}"}
    if check["must"] == "double_book":
        ok = ids == [who["target"]] and changed[0]["after"].get("start") == to and check["role"] in who
        return {"ok": ok, "why": f"changed rows {ids}; A0 must move {who['target']} into the slot held by "
                                 f"{who.get(check['role'])}"}
    raise ValueError(f"unknown fixture check {check['must']!r}")


def in_scope_rows(receipt: dict) -> set[str]:
    """Rows the receipt's own scope covered: target, collateral reads, slot occupants."""
    rows = set()
    for c in receipt["checks"]:
        if c["check"] in ("target", "collateral_candidates") and c["via"] != "pre_action_snapshot":
            rows.add(c["subject"])
        if c["check"] in ("destination_slot", "origin_slot"):
            rows |= set(c["observed"].get("occupants") or [])
            rows |= set(c["observed"].get("occupants_before_action") or [])
    return rows


def in_scope_false_approval(fixture: dict, receipt: dict, report: dict) -> bool:
    """A verified_within_scope receipt whose in-scope state is actually wrong (scorer truth)."""
    if receipt["verdict"] != "verified_within_scope":
        return False
    req = fixture["request"]
    target, db = req["target_id"], report["db"]
    changed = {r["id"]: r for r in db["changed_rows"]}
    if receipt["claim"] == "requested_change_applied":
        t = changed.get(target)
        if t is None or t["fields"] != ["start"] or t["after"]["start"] != req["to"]:
            return True
        if "destination_occupant" in roles(fixture):   # moved into a booked slot: double booking
            return True
    elif target in changed:
        return True
    scope = in_scope_rows(receipt)
    return any(rid in scope for rid in changed if rid != target) or bool(db["inserted"] or db["deleted"])
