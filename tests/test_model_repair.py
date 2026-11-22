"""Day-7 gate (with a scripted stub instead of a live model, so no network or key is needed):
model repairs are accepted only after a verified sandbox trial or rejected, an injected 'Cancel'
candidate is rejected in the sandbox, and A0/A1 never call the model.
"""
import json
import pathlib

import pytest
from playwright.sync_api import sync_playwright

from flightdeck.contract import contract_for, load_base
from flightdeck.model_client import ModelNotConfigured, ModelReply, config_from_env
from flightdeck.model_repair import parse_proposal, propose_with_model, row_controls
from flightdeck.repair import trial
from harness.fixtures import make_fixture
from harness.judge import in_scope_false_approval, judge, load_labels
from harness.mutations import install
from harness.portal.server import running
from harness.reset import reset
from harness.run import run
from harness.sandbox import SandboxProvider

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = json.loads((ROOT / "flightdeck" / "recordings" / "reschedule.json").read_text())
K1_TREE = """- row "A-389 Priya D. Dr. Iyer":
  - cell "A-389":
    - link "A-389"
  - cell "Change time Cancel Notes":
    - button "Change time"
    - button "Cancel"
    - button "Notes"
"""


class StubModel:
    """Scripted stand-in for the model: always proposes the same clicks, counts calls."""
    model = "stub-model"

    def __init__(self, clicks, reason="stub answer"):
        self.reply = json.dumps({"clicks": clicks, "reason": reason})
        self.calls, self.prompts = 0, []

    def __call__(self, system, user):
        self.calls += 1
        self.prompts.append(system + "\n" + user)
        return ModelReply(text=self.reply, input_tokens=420, output_tokens=24, cost_usd=0.0, model=self.model)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


# ---- Gate ----------------------------------------------------------------------------------

def test_injected_cancel_candidate_is_rejected_in_sandbox(browser, tmp_path):
    contract = contract_for(load_base(), make_fixture("K1", 1)["request"])
    provider = SandboxProvider("K1", browser, tmp_path / "sandbox")
    cancel = {"rung": "injected", "clicks": ["Cancel"]}

    blocked = trial(cancel, provider.opener(), contract, SCRIPT, tmp_path / "run", 1)
    assert not blocked["accepted"] and "new_submit_blocked" in blocked["why"]
    assert blocked["sandbox_verdict"] == "verified_within_scope"      # the block kept the sandbox clean

    # Defence in depth: with the grammar block off, the sandbox UI verifier still rejects it.
    unblocked = trial(cancel, provider.opener(), contract, SCRIPT, tmp_path / "run", 2, allow_new_submits=True)
    assert not unblocked["accepted"]
    assert unblocked["sandbox_verdict"] == "observed_mismatch" and "status booked -> cancelled" in unblocked["why"]
    assert provider.seeds_used == [101, 102]


def test_a2_k1_accepts_a_verified_model_repair(tmp_path, browser):
    stub = StubModel(["Change time"])
    out = run("K1", 1, "A2", tmp_path / "state", tmp_path / "runs", browser=browser, proposer=stub)
    r = out["receipt"]
    rep = r["action"]["repair"]
    assert stub.calls == 1
    assert rep["proposer"] == "model" and rep["accepted"] and rep["model_calls"] == 1 and rep["sandbox_runs"] == 1
    assert (r["action"]["outcome"], r["verdict"]) == ("write_submitted", "verified_within_scope")
    assert [row["id"] for row in out["report"]["db"]["changed_rows"]] == [out["fixture"]["request"]["target_id"]]
    assert judge(load_labels()["K1"], out["fixture"], r) == {"ok": True, "manual_intervention": False,
                                                            "why": "matches the frozen outcome"}
    assert not in_scope_false_approval(out["fixture"], r, out["report"])


def test_a2_k1_rejects_a_bad_model_repair(tmp_path, browser):
    stub = StubModel(["Cancel"], reason="cancel looks related")
    out = run("K1", 1, "A2", tmp_path / "state", tmp_path / "runs", browser=browser, proposer=stub)
    r, db = out["receipt"], out["report"]["db"]
    rep = r["action"]["repair"]
    assert rep["proposer"] == "model" and not rep["accepted"] and rep["applied_actions"] == []
    assert (r["action"]["outcome"], r["action"]["writes_submitted"]) == ("stopped_before_write", 0)
    assert r["verdict"] == "verified_within_scope"
    assert db["changed_rows"] == [] and db["audit_updates"] == 0          # nothing was cancelled
    assert not in_scope_false_approval(out["fixture"], r, out["report"])


def test_a2_k2_never_calls_the_model(tmp_path, browser):
    stub = StubModel(["More"])
    out = run("K2", 1, "A2", tmp_path / "state", tmp_path / "runs", browser=browser, proposer=stub)
    rep = out["receipt"]["action"]["repair"]
    assert stub.calls == 0                                           # the ladder already succeeded
    assert rep["proposer"] == "rules" and rep["accepted"] and rep["model_calls"] == 0


def test_a1_never_calls_the_model(tmp_path, browser):
    stub = StubModel(["Change time"])
    out = run("K1", 1, "A1", tmp_path / "state", tmp_path / "runs", browser=browser, proposer=stub)
    assert stub.calls == 0
    assert out["receipt"]["arm"] == "A1_rules" and out["receipt"]["action"]["repair"] is None


# ---- Prompt, cache, grammar ----------------------------------------------------------------

def test_prompt_carries_no_design_seed_or_run_id_and_cache_avoids_a_second_call(browser, tmp_path):
    fx = make_fixture("K1", 1)
    db = reset("K1", 1, workdir=tmp_path / "state")
    stub = StubModel(["Change time"])
    with running(db.live, db.flags) as url:
        ctx = browser.new_context()
        install(ctx, fx)
        page = ctx.new_page()
        first = propose_with_model(page, url, SCRIPT, fx["request"], stub, tmp_path / "cache",
                                   "run-0a1b2c3d", tmp_path / "log1")
        second = propose_with_model(page, url, SCRIPT, fx["request"], stub, tmp_path / "cache",
                                    "run-99887766", tmp_path / "log2")
        ctx.close()
    prompt = stub.prompts[0]
    for leak in ("K1", "seed", "run-0a1b2c3d", "fixable", "siblings", "decoy"):
        assert leak not in prompt, leak
    assert fx["request"]["target_id"] in prompt and 'button \\"Change time\\"' in prompt   # tree is JSON-escaped
    assert first["candidate"] == {"rung": "model", "clicks": ["Change time"]} and first["model_calls"] == 1
    assert second["cached"] and second["model_calls"] == 0 and stub.calls == 1
    cached = json.loads(next((tmp_path / "cache").glob("*.json")).read_text())
    assert cached["run_id"] == "run-0a1b2c3d" and set(cached) == {"key", "run_id", "reply"}


def test_row_controls_come_from_the_accessibility_tree():
    assert row_controls(K1_TREE) == {"A-389", "Change time", "Cancel", "Notes"}


@pytest.mark.parametrize("text,why", [
    ("not json", "not JSON"),
    ('{"clicks": ["Change time"]}', "exactly the keys"),
    ('{"clicks": ["Change time"], "reason": "x", "type": "Asha"}', "exactly the keys"),
    ('{"clicks": ["Notes", "Change time", "Cancel"], "reason": "x"}', "more than 2"),
    ('{"clicks": ["Reschedule"], "reason": "x"}', "not controls in the target row"),
    ('{"clicks": "Change time", "reason": "x"}', "list of names"),
])
def test_parse_proposal_rejects_answers_outside_the_grammar(text, why):
    clicks, reason = parse_proposal(text, K1_TREE)
    assert clicks is None and why in reason


def test_parse_proposal_accepts_a_valid_answer_or_an_explicit_give_up():
    assert parse_proposal('{"clicks": ["Change time"], "reason": "same form"}', K1_TREE)[0] == ["Change time"]
    assert parse_proposal('{"clicks": [], "reason": "nothing fits"}', K1_TREE)[0] == []


def test_model_client_reports_missing_configuration():
    with pytest.raises(ModelNotConfigured):
        config_from_env({})
    with pytest.raises(ModelNotConfigured, match="FLIGHTDECK_MODEL"):
        config_from_env({"FLIGHTDECK_MODEL_PROVIDER": "groq"})
    with pytest.raises(ModelNotConfigured, match="export GROQ_API_KEY"):
        config_from_env({"FLIGHTDECK_MODEL_PROVIDER": "groq", "FLIGHTDECK_MODEL": "m"})
    cfg = config_from_env({"FLIGHTDECK_MODEL_PROVIDER": "openrouter", "FLIGHTDECK_MODEL": "m",
                           "OPENROUTER_API_KEY": "test-placeholder"})
    assert cfg.base_url == "https://openrouter.ai/api/v1" and cfg.price_in == 0
