"""Intent contract (runtime): draft from the demo, confirm in three lines, reuse per request.

The draft comes from the recorded demo's visible before/after of the target's detail page. The
operator confirms three lines (Change, Preserve, If blocked). For a fresh request the harness
supplies target ID, from and to; the confirmed preserve, if-blocked and scope lines are reused.

CLI: python -m flightdeck.contract confirm --demo flightdeck/recordings/reschedule.demo.json \
         --by operator --out contract.json
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flightdeck.receipt_rules import schema_errors

ROOT = Path(__file__).resolve().parents[1]
BASE_CONTRACT = ROOT / "examples" / "contract.A-104.json"
CONTRACT_SCHEMA = ROOT / "schemas" / "intent-contract.schema.json"


CONTRACT_FIELDS = ["start", "clinician", "patient", "duration_min", "status"]
SHORT_NAMES = {"duration_min": "duration"}
IST = timezone(timedelta(hours=5, minutes=30))
STANDARD_IF_BLOCKED = [
    {"when": "destination_occupied", "then": "refuse_no_change", "source": "operator"},
    {"when": "target_not_found", "then": "stop_and_ask", "source": "policy"},
    {"when": "start_state_differs", "then": "stop_and_ask", "source": "policy"},
    {"when": "readback_unavailable", "then": "stop_and_ask", "source": "policy"},
]
LAST_UPDATED = {"effect": "'Last updated' time on the detail page changes", "visible_in_ui": True,
                "treatment": "ignore"}
NOTIFICATION = {"effect": "Patient notification is sent", "visible_in_ui": False,
                "treatment": "report_if_seen"}   # policy default: the UI never shows it


class ContractInvalid(ValueError):
    pass


def short(iso: str) -> str:
    """'2026-12-15T16:00:00+05:30' -> 'Tue 15 Dec 16:00'."""
    return datetime.fromisoformat(iso).strftime("%a %d %b %H:%M")


def load_base() -> dict:
    return json.loads(BASE_CONTRACT.read_text())


def contract_for(base: dict, request: dict) -> dict:
    c = copy.deepcopy(base)
    target = request["target_id"]
    c["contract_id"] = f"ctr-{target}-001"
    c["target"]["id"] = target
    c["change"][0]["from"] = request["from"]
    c["change"][0]["to"] = request["to"]
    return check_schema(c)


def requested_lines(contract: dict, clinician: str) -> list[str]:
    ch = contract["change"][0]
    target = contract["target"]["id"]
    return [
        f"Change: {target} {ch['field']} {short(ch['from'])} -> {short(ch['to'])}",
        "Preserve: " + ", ".join(contract["preserve"]),
        f"If blocked: {clinician} busy {short(ch['to'])} -> change nothing and report; "
        "target missing, start already moved, or no readback -> stop and ask",
    ]


def check_schema(contract: dict) -> dict:
    errors = schema_errors(json.loads(CONTRACT_SCHEMA.read_text()), contract)
    if errors:
        raise ContractInvalid("; ".join(errors))
    return contract


def draft_from_demo(demo: dict) -> dict:
    """Draft from what the demo visibly changed on the target's detail page."""
    before, after, target = demo["before"], demo["after"], demo["target_id"]
    unreadable = [f for f in CONTRACT_FIELDS if f not in before or f not in after]
    if unreadable:
        raise ContractInvalid(f"demo did not show {unreadable}; cannot draft")
    changed = [f for f in CONTRACT_FIELDS if before[f] != after[f]]
    if changed != ["start"]:
        raise ContractInvalid(f"the pilot supports exactly one changed field (start); demo changed {changed}")
    incidental = []
    if before.get("last_updated") != after.get("last_updated"):
        incidental.append(dict(LAST_UPDATED))
    incidental.append(dict(NOTIFICATION))
    return {
        "contract_id": f"ctr-{target}-001",
        "task": "reschedule_appointment",
        "target": {"id": target},
        "change": [{"field": "start", "from": before["start"], "to": after["start"]}],
        "preserve": [f for f in CONTRACT_FIELDS if f not in changed],
        "if_blocked": copy.deepcopy(STANDARD_IF_BLOCKED),
        "scope": {"checks": ["target", "collateral_candidates", "destination_slot", "origin_slot"]},
        "incidental": incidental,
    }


def _side_effect(i: dict) -> str:
    text = i["effect"]
    for tail in (" on the detail page changes", " changes", " is sent"):
        text = text.removesuffix(tail)
    text = text[0].lower() + text[1:] if not text.startswith("'") else text
    if not i["visible_in_ui"]:
        return f"{text} (not visible, reported as unknown)"
    return f"{text} ({'ignored' if i['treatment'] == 'ignore' else 'reported if seen'})"


def confirmation_text(contract: dict, clinician: str) -> str:
    ch, target = contract["change"][0], contract["target"]["id"]
    preserve = ", ".join(f"{p} ({clinician})" if p == "clinician" else SHORT_NAMES.get(p, p)
                         for p in contract["preserve"])
    lines = [f"Change      {target} {ch['field']}  {short(ch['from'])}  ->  {short(ch['to'])}",
             f"Preserve    {preserve}"]
    blocked = []
    for b in contract["if_blocked"]:
        if b["when"] == "destination_occupied":
            act = "change nothing, report" if b["then"] == "refuse_no_change" else "stop, ask"
            blocked.append(f"{clinician} already booked {short(ch['to'])} -> {act}   [{b['source']}]")
    policy = [b for b in contract["if_blocked"] if b["when"] != "destination_occupied"]
    if policy:
        sources = sorted({b["source"] for b in policy})
        blocked.append(f"{target} missing, already moved, or can't be read back -> stop, ask  "
                       f"[{', '.join(sources)}]")
    lines.append("If blocked  " + ("\n            ".join(blocked) or "(none)"))
    if contract.get("incidental"):
        n = len(contract["incidental"])
        lines.append(f"  + {n} side effect{'s' if n != 1 else ''}: "
                     + ", ".join(_side_effect(i) for i in contract["incidental"]))
    return "\n".join(lines)


def confirm(draft: dict, by: str, at: str | None = None) -> dict:
    c = copy.deepcopy(draft)
    c["confirmed"] = {"by": by, "at": at or datetime.now(IST).isoformat(timespec="seconds")}
    return check_schema(c)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m flightdeck.contract")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cf = sub.add_parser("confirm", help="draft from a recorded demo and confirm the three lines")
    cf.add_argument("--demo", required=True)
    cf.add_argument("--by", required=True)
    cf.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    demo = json.loads(Path(args.demo).read_text())
    draft = draft_from_demo(demo)
    print(confirmation_text(draft, demo["before"]["clinician"]))
    if input("\nConfirm these three lines? [y/N] ").strip().lower() not in {"y", "yes"}:
        print("Not confirmed; nothing written.")
        sys.exit(1)
    contract = confirm(draft, by=args.by)
    Path(args.out).write_text(json.dumps(contract, indent=2) + "\n")
    print(f"confirmed -> {args.out}")


if __name__ == "__main__":
    main()
