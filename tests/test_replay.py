"""Day-3 gate: recorded script, A0 replay, R1 browser mutation, S1 backend miswrite.

These are fixture checks: naive replay (A0) must produce the fault's wrong write. No receipt
is sealed here; receipts arrive with the Day-4 verifier.
"""
import inspect
import json
import pathlib

import pytest
from playwright.sync_api import sync_playwright

from flightdeck.executor import replay_a0
from flightdeck.record import record
from harness.fixtures import make_fixture
from harness.mutations import install
from harness.portal.server import running
from harness.reset import reset
from harness.score import score

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "flightdeck" / "recordings" / "reschedule.json"
REQUEST_KEYS = ("target_id", "from", "to", "clinician")


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def run_a0(design, seed, workdir, browser):
    """Harness side: reset, start the portal with its flags, install any mutation, hand over a page."""
    fx = make_fixture(design, seed)
    db = reset(design, seed, workdir=workdir)
    request = {k: fx["request"][k] for k in REQUEST_KEYS}   # all the executor learns about the case
    with running(db.live, db.flags) as url:
        ctx = browser.new_context()
        install(ctx, fx)
        try:
            result = replay_a0(ctx.new_page(), url, json.loads(SCRIPT_PATH.read_text()), request)
        finally:
            ctx.close()
    return fx, result, score(db.pristine, db.live)


def moved(fx, row_index):
    row = fx["rows"][row_index]
    return {"id": row["id"], "fields": ["start"],
            "before": {"start": row["start"]}, "after": {"start": fx["request"]["to"]}}


# ---- Gate ----------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a0_on_r1_moves_the_decoy(seed, tmp_path, browser):
    fx, result, report = run_a0("R1", seed, tmp_path, browser)
    assert result["writes_submitted"] == 1
    assert report["changed_rows"] == [moved(fx, 1)]          # the decoy, not the target
    assert report["audit_updates"] == 1


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_s1_shows_success_while_the_wrong_row_moves(seed, tmp_path, browser):
    fx, result, report = run_a0("S1", seed, tmp_path, browser)
    assert result["writes_submitted"] == 1
    assert result["success_text_seen"] is True               # "Appointment updated"
    assert report["changed_rows"] == [moved(fx, 1)]          # backend moved the decoy
    assert fx["request"]["target_id"] not in [r["id"] for r in report["changed_rows"]]


# ---- Supporting behaviour ------------------------------------------------------------------

def test_a0_on_c0_moves_the_target(tmp_path, browser):
    fx, result, report = run_a0("C0", 1, tmp_path, browser)
    assert result["success_text_seen"] is True
    assert report["changed_rows"] == [moved(fx, 0)]
    assert report["audit_updates"] == 1


def test_r1_mutation_leaves_no_markers(tmp_path, browser):
    fx = make_fixture("R1", 1)
    db = reset("R1", 1, workdir=tmp_path)
    js = "() => ({rows: [...document.querySelectorAll('tbody tr')].map(r => r.outerHTML),"\
         " globals: Object.keys(window).sort(), html: document.documentElement.outerHTML.length})"
    seen = {}
    with running(db.live, db.flags) as url:
        for mutated in (False, True):
            ctx = browser.new_context()
            if mutated:
                install(ctx, fx)
            page = ctx.new_page()
            page.goto(f"{url}/appointments")
            seen[mutated] = page.evaluate(js)
            ctx.close()
    plain, mut = seen[False], seen[True]
    assert sorted(mut["rows"]) == sorted(plain["rows"])      # same rows, same markup
    assert mut["rows"][:2] == plain["rows"][:2][::-1]        # only rows 1 and 2 swapped
    assert mut["rows"][2:] == plain["rows"][2:]
    assert mut["globals"] == plain["globals"]                # no window globals added
    assert mut["html"] == plain["html"]                      # no extra nodes or attributes


def test_recording_matches_the_canonical_portal(tmp_path, browser):
    db = reset("C0", 0, workdir=tmp_path)
    with running(db.live) as url:
        page = browser.new_page()
        script = record(page, url, "A-104", "2026-12-17T11:00")
        page.close()
    assert script == json.loads(SCRIPT_PATH.read_text())


def test_executor_gets_no_design_or_seed():
    assert list(inspect.signature(replay_a0).parameters) == ["page", "base_url", "script", "request"]
    assert set(make_fixture("R1", 1)["request"]) == set(REQUEST_KEYS)
    assert "R1" not in SCRIPT_PATH.read_text() and "seed" not in SCRIPT_PATH.read_text()
