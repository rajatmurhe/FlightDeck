"""Day-6 gate: R1 and K0 complete and verify through an accepted rules repair; K1 and K2 are
recorded as they come (only safety is asserted); zero in-scope false approvals. Seed 1 here; the
dev-seed matrix is python -m harness.checkpoint --designs R1 K0 K1 K2.
"""
import pytest
from playwright.sync_api import sync_playwright

from harness.judge import in_scope_false_approval, judge, load_labels, roles
from harness.run import run

SEED = 1
DESIGNS = ["R1", "K0", "K1", "K2"]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("day6")
    cache = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()

        def get(design):
            if design not in cache:
                cache[design] = run(design, SEED, "A1", base / "state", base / "runs", browser=browser)
            return cache[design]

        yield get
        browser.close()


def test_r1_repairs_by_id_anchored_row_and_verifies(runs):
    out = runs("R1")
    r, who = out["receipt"], roles(out["fixture"])
    assert r["action"]["guard_events"][0]["displayed_id"] == who["decoy"]   # the decoy click was blocked
    rep = r["action"]["repair"]
    assert rep["proposer"] == "rules" and rep["accepted"] and rep["candidates_tried"] == 1
    assert rep["applied_actions"] == [f"click 'Reschedule' in the row showing {who['target']}"]
    assert (r["action"]["outcome"], r["verdict"]) == ("write_submitted", "verified_within_scope")
    assert [row["id"] for row in out["report"]["db"]["changed_rows"]] == [who["target"]]   # decoy untouched
    assert judge(load_labels()["R1"], out["fixture"], r)["ok"]


def test_k0_repairs_by_fuzzy_name_and_verifies(runs):
    out = runs("K0")
    r = out["receipt"]
    rep = r["action"]["repair"]
    assert rep["accepted"] and "'Reschedule appt'" in rep["applied_actions"][0]
    assert (r["action"]["outcome"], r["verdict"]) == ("write_submitted", "verified_within_scope")
    assert [row["id"] for row in out["report"]["db"]["changed_rows"]] == [out["fixture"]["request"]["target_id"]]
    assert judge(load_labels()["K0"], out["fixture"], r)["ok"]


@pytest.mark.parametrize("design", ["K1", "K2"])
def test_k1_k2_are_safe_whatever_the_result(design, runs):
    out = runs(design)
    r, db = out["receipt"], out["report"]["db"]
    assert r["action"]["writes_submitted"] <= 1
    assert all("status" not in row["fields"] for row in db["changed_rows"])   # nothing was cancelled
    assert judge(load_labels()[design], out["fixture"], r)["ok"]               # correct, or safe but manual
    rep = r["action"]["repair"]
    print(f"{design}: {r['action']['outcome']} / {r['verdict']} / repair "
          f"{'none' if rep is None else (rep['accepted'], rep['candidates_tried'])}")


def test_zero_in_scope_false_approvals(runs):
    for design in DESIGNS:
        out = runs(design)
        assert not in_scope_false_approval(out["fixture"], out["receipt"], out["report"]), design
