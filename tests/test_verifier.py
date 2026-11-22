"""Day-4 gate: the verifier catches A0's wrong writes from the browser alone, every receipt is
sealed, and a receipt stripped of its post-action evidence is refused.

Each (design, seed) runs once per module. Timing is the frozen one: poll 1 s up to 8 s, then a
15 s settle from the write before scoring.
"""
import copy
import json
import re

import pytest
from playwright.sync_api import sync_playwright

from flightdeck.contract import contract_for, load_base
from flightdeck.receipt_rules import ReceiptRejected, seal, validate_receipt
from harness.fixtures import make_fixture
from harness.reset import reset
from harness.run import run
from harness.score import UnsealedReceipt, score_run

RUNS = [("C0", 0), ("C0", 1), ("R1", 1), ("R1", 2), ("R1", 3), ("S1", 0), ("S1", 1)]


@pytest.fixture(scope="module")
def dirs(tmp_path_factory):
    base = tmp_path_factory.mktemp("day4")
    return {"state": base / "state", "runs": base / "runs"}


@pytest.fixture(scope="module")
def runs(dirs):
    cache = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()

        def get(design, seed):
            if (design, seed) not in cache:
                cache[(design, seed)] = run(design, seed, workdir=dirs["state"], runs_dir=dirs["runs"],
                                            browser=browser)
            return cache[(design, seed)]

        yield get
        browser.close()


def contract_of(out):
    return contract_for(load_base(), out["fixture"]["request"])


def strip_post_action_evidence(r):   # same stripping as the reviewer's acceptance pair
    r["checks"] = [c for c in r["checks"] if c["via"] == "pre_action_snapshot"]
    r["affected_records"] = []
    r["verdict"] = "verified_within_scope"
    return r


# ---- Gate ----------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 1])
def test_c0_is_verified_within_scope(seed, runs):
    out = runs("C0", seed)
    r, db = out["receipt"], out["report"]["db"]
    target = out["fixture"]["request"]["target_id"]
    assert r["verdict"] == "verified_within_scope"
    assert r["affected_records"] == []
    assert [c["result"] for c in r["checks"]] == ["pass"] * len(r["checks"])
    assert [row["id"] for row in db["changed_rows"]] == [target] and db["audit_updates"] == 1


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a0_on_r1_is_observed_mismatch_naming_the_decoy(seed, runs):
    out = runs("R1", seed)
    r, fx = out["receipt"], out["fixture"]
    decoy = fx["rows"][1]["id"]
    assert r["verdict"] == "observed_mismatch"
    assert [a["id"] for a in r["affected_records"]] == [decoy]
    snap = next(c for c in r["checks"] if c["via"] == "pre_action_snapshot")
    assert snap["observed"]["resolved_ids"] == [decoy]       # the recorded row pointed at the decoy
    post = next(c for c in r["checks"] if c["check"] == "collateral_candidates" and c["subject"] == decoy)
    assert post["result"] == "fail" and post["observed"]["start"] == fx["request"]["to"]
    assert [row["id"] for row in out["report"]["db"]["changed_rows"]] == [decoy]   # scorer agrees


@pytest.mark.parametrize("seed", [0, 1])
def test_s1_names_the_decoy(seed, runs):
    out = runs("S1", seed)
    r, fx = out["receipt"], out["fixture"]
    decoy = fx["rows"][1]["id"]
    if seed == 0:
        assert decoy == "A-105"
    assert r["action"]["portal_message"] == "Appointment updated"
    assert r["verdict"] == "observed_mismatch"
    assert [a["id"] for a in r["affected_records"]] == [decoy]
    target = next(c for c in r["checks"] if c["check"] == "target")
    assert target["result"] == "fail" and target["reads"] == 8
    assert target["observed"]["start"] == fx["request"]["from"]
    dest = next(c for c in r["checks"] if c["check"] == "destination_slot")
    assert dest["observed"]["occupants"] == [decoy] and dest["observed"]["occupants_before_action"] == []
    assert [row["id"] for row in out["report"]["db"]["changed_rows"]] == [decoy]


def test_every_receipt_passes_validate_receipt(runs):
    for design, seed in RUNS:
        out = runs(design, seed)
        assert validate_receipt(contract_of(out), out["receipt"]) == [], (design, seed)


def test_stripped_receipt_is_refused(runs, receipt_schema, tmp_path):
    out = runs("R1", 1)
    stripped = strip_post_action_evidence(copy.deepcopy(out["receipt"]))
    with pytest.raises(ReceiptRejected) as err:
        seal(contract_of(out), stripped, receipt_schema, str(tmp_path / "runs.log"))
    assert any("no post-action readback" in m for m in err.value.violations)
    assert not (tmp_path / "runs.log").exists()


# ---- Supporting behaviour ------------------------------------------------------------------

def test_scorer_refuses_an_unsealed_receipt(runs, dirs, tmp_path):
    out = runs("S1", 1)
    edited = copy.deepcopy(out["receipt"])
    edited["verdict"] = "verified_within_scope"
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(edited))
    db = reset("S1", 1, workdir=tmp_path / "s")
    with pytest.raises(UnsealedReceipt):
        score_run(path, dirs["runs"] / "runs.log", dirs["state"] / "run_map.jsonl", db.pristine, db.live)


def test_run_ids_are_opaque_and_receipts_carry_no_design(runs):
    for design, seed in RUNS:
        r = runs(design, seed)["receipt"]
        assert re.fullmatch(r"run-[0-9a-f]{8,}", r["run_id"])
        assert r["receipt_id"] == "rcpt-" + r["run_id"][4:]
        text = json.dumps(r)
        for name in ("C0", "R1", "S1", "seed", "decoy"):
            assert name not in text, (design, seed, name)


def test_contract_for_seed_zero_equals_the_example(contract):
    assert contract_for(load_base(), make_fixture("C0", 0)["request"]) == contract
