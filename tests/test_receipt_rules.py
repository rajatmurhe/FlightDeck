"""Evidence checks: a receipt may only be sealed if its evidence supports its verdict."""
import pytest

from flightdeck.receipt_rules import ReceiptRejected, compute_verdict, seal, validate_receipt


def _strip_post_action_evidence(r):
    r["checks"] = [c for c in r["checks"] if c["via"] == "pre_action_snapshot"]
    r["affected_records"] = []
    r["verdict"] = "verified_within_scope"
    return r


# ---- Reviewer's Day-1 acceptance pair -------------------------------------------------

def test_s1_without_post_action_evidence_cannot_be_sealed_as_verified(contract, s1, receipt_schema, tmp_path):
    receipt = _strip_post_action_evidence(s1)
    assert compute_verdict(receipt["checks"]) == "verified_within_scope"  # the old formula alone is fooled
    with pytest.raises(ReceiptRejected) as err:
        seal(contract, receipt, receipt_schema, str(tmp_path / "runs.log"))
    assert any("no post-action readback of A-104" in m for m in err.value.violations)
    assert not (tmp_path / "runs.log").exists()


def test_intact_s1_seals_as_observed_mismatch(contract, s1, receipt_schema, tmp_path):
    assert validate_receipt(contract, s1) == []
    assert compute_verdict(s1["checks"]) == "observed_mismatch"
    digest = seal(contract, s1, receipt_schema, str(tmp_path / "runs.log"))
    assert (tmp_path / "runs.log").read_text() == f"run-5c1e9a7d {digest}\n"


# ---- Other ways to claim more than the evidence shows ---------------------------------

def test_post_action_checks_without_reads_or_evidence_are_rejected(contract, s1):
    for c in s1["checks"]:
        if c["via"] != "pre_action_snapshot":
            c["reads"], c["evidence"] = 0, []
    assert any("without reads or evidence" in m for m in validate_receipt(contract, s1))


def test_refusal_cannot_report_a_write(contract, o1):
    o1["action"]["writes_submitted"] = 1
    assert "refused_no_change requires writes_submitted == 0" in validate_receipt(contract, o1)


def test_o1_refusal_is_verified_no_change(contract, o1):
    assert validate_receipt(contract, o1) == []
    assert o1["claim"] == "no_change" and o1["verdict"] == "verified_within_scope"


def test_target_must_show_the_requested_id(contract, s1):
    s1["checks"][0]["displayed_id"] = "A-105"
    assert "target readback displayed 'A-105', not A-104" in validate_receipt(contract, s1)


def test_pass_must_match_the_observed_fields(contract, s1):
    s1["checks"][0]["result"] = "pass"  # observed start is still Tuesday
    assert any("'pass' but fields" in m for m in validate_receipt(contract, s1))


def test_expected_values_come_from_the_contract(contract, o1):
    o1["checks"][0]["expected"]["start"] = o1["checks"][0]["observed"]["start"] = "2026-12-18T10:00:00+05:30"
    assert any("does not match the contract" in m for m in validate_receipt(contract, o1))


def test_verdict_must_follow_the_rule(contract, s1):
    s1["verdict"] = "unable_to_verify"
    assert any("does not follow the rule" in m for m in validate_receipt(contract, s1))


def test_row_at_risk_before_the_click_must_be_read_after_it(contract, o1):
    o1["checks"][1]["observed"]["resolved_ids"] = ["A-105"]  # recorded locator pointed at the decoy
    assert "A-105 was at risk before the click but was never read after it" in validate_receipt(contract, o1)
    o1["checks"].append({
        "check": "collateral_candidates", "subject": "A-105", "via": "search_detail", "displayed_id": "A-105",
        "expected": {"start": "2026-12-15T16:30:00+05:30", "clinician": "Dr. Rao", "patient": "Ravi K.",
                     "duration_min": 30, "status": "booked"},
        "observed": {"start": "2026-12-15T16:30:00+05:30", "clinician": "Dr. Rao", "patient": "Ravi K.",
                     "duration_min": 30, "status": "booked"},
        "result": "pass", "reads": 1, "evidence": ["runs/9b04e6f1/post-detail-A-105.png"]})
    assert validate_receipt(contract, o1) == []


def test_affected_record_needs_its_own_observation(contract, s1):
    s1["checks"][2]["observed"]["occupants"] = []  # S2: the miswrite landed outside scope
    assert "A-105 is named as affected without a post-action observation of it" in validate_receipt(contract, s1)


def test_guard_block_then_write_needs_an_accepted_repair(contract, s1):
    s1["action"]["guard_events"] = [{"step": 3, "expected_id": "A-104", "displayed_id": "A-105",
                                     "action": "blocked_click"}]
    assert "a guard blocked a click, so any later write needs an accepted repair" in validate_receipt(contract, s1)
