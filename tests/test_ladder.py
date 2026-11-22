"""The rules ladder proposes in a fixed order, read-only, within budget; sandbox seeds are 101+."""
import json
import pathlib

import pytest
from playwright.sync_api import sync_playwright

from flightdeck.ladder import BUDGET, propose
from harness.fixtures import make_fixture
from harness.mutations import install
from harness.portal.server import running
from harness.reset import reset
from harness.sandbox import SandboxProvider
from harness.score import score

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = json.loads((ROOT / "flightdeck" / "recordings" / "reschedule.json").read_text())


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def proposals(design, browser, workdir, seed=1):
    fx = make_fixture(design, seed)
    db = reset(design, seed, workdir=workdir)
    with running(db.live, db.flags) as url:
        ctx = browser.new_context()
        install(ctx, fx)
        page = ctx.new_page()
        cands = propose(page, url, SCRIPT, fx["request"])
        expanded = page.locator("button[aria-haspopup]").evaluate_all(
            "bs => bs.map(b => b.getAttribute('aria-expanded'))")
        ctx.close()
    return cands, score(db.pristine, db.live), expanded


def test_r1_relocates_to_the_id_anchored_row(browser, tmp_path):
    cands, _, _ = proposals("R1", browser, tmp_path)
    assert cands == [{"rung": "id_anchored_exact", "clicks": ["Reschedule"]}]


def test_k0_proposes_the_fuzzy_name(browser, tmp_path):
    cands, _, _ = proposals("K0", browser, tmp_path)
    assert cands == [{"rung": "fuzzy_name", "clicks": ["Reschedule appt"]}]


def test_k1_proposes_nothing_and_never_cancel(browser, tmp_path):
    cands, _, _ = proposals("K1", browser, tmp_path)
    assert cands == []


def test_k2_proposes_only_button_then_menu(browser, tmp_path):
    cands, _, _ = proposals("K2", browser, tmp_path)
    assert cands == [{"rung": "only_button", "clicks": ["More"]},
                     {"rung": "row_menu", "clicks": ["More", "Reschedule"]}]


def test_proposing_clicks_nothing(browser, tmp_path):
    for design in ("K1", "K2"):
        cands, report, expanded = proposals(design, browser, tmp_path / design)
        assert report["changed_rows"] == [] and report["audit_updates"] == 0
        assert set(expanded) <= {"false"}       # no menu was opened
        assert len(cands) <= BUDGET
        assert all(len(c["clicks"]) <= 2 for c in cands)


def test_sandbox_seeds_start_at_101(browser, tmp_path):
    with pytest.raises(ValueError):
        SandboxProvider("K0", browser, tmp_path, first_seed=13)
    provider = SandboxProvider("K0", browser, tmp_path)
    for _ in range(2):
        with provider.opener()() as sb:
            assert set(sb.request) == {"target_id", "from", "to", "clinician"}
    assert provider.seeds_used == [101, 102]
