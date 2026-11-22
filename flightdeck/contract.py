"""Intent contract per request (runtime).

The operator confirms one contract (examples/contract.A-104.json). For a fresh request the
harness supplies target ID, from and to; the confirmed preserve, if-blocked and scope lines are
reused unchanged. Day 5 adds drafting and the CLI confirmation.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

from flightdeck.receipt_rules import schema_errors

ROOT = Path(__file__).resolve().parents[1]
BASE_CONTRACT = ROOT / "examples" / "contract.A-104.json"
CONTRACT_SCHEMA = ROOT / "schemas" / "intent-contract.schema.json"


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
    errors = schema_errors(json.loads(CONTRACT_SCHEMA.read_text()), c)
    if errors:
        raise ContractInvalid("; ".join(errors))
    return c


def requested_lines(contract: dict, clinician: str) -> list[str]:
    ch = contract["change"][0]
    target = contract["target"]["id"]
    return [
        f"Change: {target} {ch['field']} {short(ch['from'])} -> {short(ch['to'])}",
        "Preserve: " + ", ".join(contract["preserve"]),
        f"If blocked: {clinician} busy {short(ch['to'])} -> change nothing and report; "
        "target missing, start already moved, or no readback -> stop and ask",
    ]
