"""Shape checks: examples are valid, broken variants are rejected, audit trigger logs one row."""
import copy
import sqlite3

import pytest

from flightdeck.receipt_rules import format_checker, schema_errors


def test_rfc3339_checking_is_on():
    # v0.1 silently skipped date-time checks without rfc3339-validator and still exited 0.
    assert "date-time" in format_checker().checkers


@pytest.mark.parametrize("name", ["contract", "s1", "o1"])
def test_examples_match_their_schema(name, request, contract_schema, receipt_schema):
    doc = request.getfixturevalue(name)
    schema = contract_schema if name == "contract" else receipt_schema
    assert schema_errors(schema, doc) == []


def _set(doc, path, value):
    *head, last = path
    for k in head:
        doc = doc[k]
    doc[last] = value


CONTRACT_BREAKS = {
    "required invisible notification": (["incidental", 1, "treatment"], "required"),
    "if_blocked sourced from demo": (["if_blocked", 0, "source"], "demo"),
    "scope without target": (["scope", "checks"], ["destination_slot"]),
    "non-RFC3339 time": (["change", 0, "to"], "Thu 11am"),
}

RECEIPT_BREAKS = {
    "second write": (["action", "writes_submitted"], 2),
    "empty unknown": (["unknown"], []),
    "affected record without evidence": (["affected_records", 0, "evidence"], []),
    "over attempt budget": (["action", "repair"], {"proposer": "model", "candidates_tried": 4, "accepted": True,
                                                   "applied_actions": ["a"], "sandbox_runs": 4, "model_calls": 4,
                                                   "model_cost_usd": 0.01}),
    "repair longer than 2 actions": (["action", "repair"], {"proposer": "model", "candidates_tried": 1, "accepted": True,
                                                            "applied_actions": ["a", "b", "c"], "sandbox_runs": 1,
                                                            "model_calls": 1, "model_cost_usd": 0.01}),
    # added after review
    "refused with a write": (["action", "outcome"], "refused_no_change"),
    "write with claim no_change": (["claim"], "no_change"),
    "run id that names the fixture": (["run_id"], "run-S1-seed0-A1"),
    "target read from a pre-action snapshot": (["checks", 0, "via"], "pre_action_snapshot"),
}


@pytest.mark.parametrize("name", sorted(CONTRACT_BREAKS))
def test_broken_contracts_are_rejected(name, contract, contract_schema):
    doc = copy.deepcopy(contract)
    _set(doc, *CONTRACT_BREAKS[name])
    assert schema_errors(contract_schema, doc), f"schema accepted: {name}"


@pytest.mark.parametrize("name", sorted(RECEIPT_BREAKS))
def test_broken_receipts_are_rejected(name, s1, receipt_schema):
    _set(s1, *RECEIPT_BREAKS[name])
    assert schema_errors(receipt_schema, s1), f"schema accepted: {name}"


def test_one_update_writes_one_audit_row(root):
    db = sqlite3.connect(":memory:")
    db.executescript((root / "harness/schema.sql").read_text())
    db.executescript("""
        INSERT INTO clinicians VALUES ('C-1','Dr. Rao');
        INSERT INTO patients VALUES ('P-1','Asha N.'), ('P-2','Ravi K.');
        INSERT INTO appointments VALUES
          ('A-104','P-1','C-1','2026-12-15T16:00:00+05:30',30,'booked','t0'),
          ('A-105','P-2','C-1','2026-12-15T16:30:00+05:30',30,'booked','t0');
        DELETE FROM audit_log;
    """)
    db.execute("UPDATE appointments SET start='2026-12-17T11:00:00+05:30', updated_at='t1' WHERE id='A-104'")
    rows = db.execute("SELECT op, appt_id, json_extract(before,'$.start'), json_extract(after,'$.start') "
                      "FROM audit_log").fetchall()
    assert rows == [("update", "A-104", "2026-12-15T16:00:00+05:30", "2026-12-17T11:00:00+05:30")]
