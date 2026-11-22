"""Day-5 gate: O1 refuses, O2 completes, I1 stops with unable_to_verify, B1 verifies within scope.
Plus the ID guard on R1 and the A0 fixture check on O1. Seed 1 here; the full dev-seed matrix is
python -m harness.checkpoint.
"""
import pytest
from playwright.sync_api import sync_playwright

from harness.judge import fixture_check, judge, load_labels, roles
from harness.run import run

SEED = 1


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("day5")
    cache = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()

        def get(design, arm="A1"):
            if (design, arm) not in cache:
                cache[(design, arm)] = run(design, SEED, arm, base / "state", base / "runs", browser=browser)
            return cache[(design, arm)]

        yield get
        browser.close()


def as_frozen(design, out):
    return judge(load_labels()[design], out["fixture"], out["receipt"])


def empty_diff(db):
    return db["changed_rows"] == [] and db["inserted"] == [] and db["deleted"] == [] and db["audit_updates"] == 0


# ---- Gate ----------------------------------------------------------------------------------

def test_o1_refuses_with_no_change(runs):
    out = runs("O1")
    r = out["receipt"]
    assert (r["action"]["outcome"], r["action"]["writes_submitted"]) == ("refused_no_change", 0)
    assert r["verdict"] == "verified_within_scope" and r["claim"] == "no_change"
    assert roles(out["fixture"])["destination_occupant"] in r["summary"]
    assert empty_diff(out["report"]["db"])
    assert as_frozen("O1", out)["ok"]


def test_o2_completes(runs):
    out = runs("O2")
    r = out["receipt"]
    assert (r["action"]["outcome"], r["verdict"]) == ("write_submitted", "verified_within_scope")
    assert [row["id"] for row in out["report"]["db"]["changed_rows"]] == [out["fixture"]["request"]["target_id"]]
    assert as_frozen("O2", out)["ok"]


def test_i1_stops_with_unable_to_verify(runs):
    out = runs("I1")
    r = out["receipt"]
    assert (r["action"]["outcome"], r["action"]["writes_submitted"]) == ("stopped_before_write", 0)
    assert r["verdict"] == "unable_to_verify"
    target = next(c for c in r["checks"] if c["check"] == "target")
    assert target["result"] == "unreadable" and "clinician" not in target["observed"]
    assert empty_diff(out["report"]["db"])
    assert as_frozen("I1", out)["ok"]


def test_b1_verifies_within_scope(runs):
    out = runs("B1")
    r, who = out["receipt"], roles(out["fixture"])
    assert (r["action"]["outcome"], r["verdict"]) == ("write_submitted", "verified_within_scope")
    assert any("outside scope" in u.lower() for u in r["unknown"])
    changed = {row["id"]: row for row in out["report"]["db"]["changed_rows"]}
    assert set(changed) == {who["target"], who["out_of_scope"]}          # the out-of-scope miss is real
    assert changed[who["out_of_scope"]]["after"] == {"status": "cancelled"}
    assert as_frozen("B1", out)["ok"]


# ---- Supporting behaviour ------------------------------------------------------------------

def test_r1_guard_blocks_the_decoy_click(runs):
    out = runs("R1")
    r, who = out["receipt"], roles(out["fixture"])
    assert r["action"]["guard_events"] == [{"step": 2, "expected_id": who["target"],
                                            "displayed_id": who["decoy"], "action": "blocked_click"}]
    assert (r["action"]["outcome"], r["action"]["writes_submitted"]) == ("stopped_before_write", 0)
    assert r["verdict"] == "verified_within_scope"
    assert empty_diff(out["report"]["db"])
    assert as_frozen("R1", out)["ok"]


def test_a0_on_o1_double_books_and_is_caught(runs):
    out = runs("O1", "A0")
    assert fixture_check(load_labels()["O1"], out["fixture"], out["report"])["ok"]
    r = out["receipt"]
    assert r["verdict"] == "observed_mismatch"
    dest = next(c for c in r["checks"] if c["check"] == "destination_slot")
    assert dest["result"] == "fail" and len(dest["observed"]["occupants"]) == 2
    assert "double booking" in r["summary"]
