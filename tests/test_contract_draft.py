"""Contract drafted from the recorded demo, confirmed in three lines, schema-checked."""
import json
import pathlib

import pytest

from flightdeck.contract import ContractInvalid, confirm, confirmation_text, draft_from_demo, main

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO = ROOT / "flightdeck" / "recordings" / "reschedule.demo.json"


def test_draft_from_the_demo_confirms_to_the_example_contract(contract):
    draft = draft_from_demo(json.loads(DEMO.read_text()))
    assert "confirmed" not in draft
    assert confirm(draft, by=contract["confirmed"]["by"], at=contract["confirmed"]["at"]) == contract


def test_three_line_confirmation_names_target_clinician_and_side_effects():
    demo = json.loads(DEMO.read_text())
    text = confirmation_text(draft_from_demo(demo), demo["before"]["clinician"])
    lines = text.splitlines()
    assert lines[0].startswith("Change      A-104 start  Tue 15 Dec 16:00  ->  Thu 17 Dec 11:00")
    assert lines[1] == "Preserve    clinician (Dr. Rao), patient, duration, status"
    assert lines[2].startswith("If blocked  Dr. Rao already booked Thu 17 Dec 11:00 -> change nothing, report")
    assert "[operator]" in lines[2] and "[policy]" in lines[3]
    assert lines[4].startswith("  + 2 side effects:") and "not visible" in lines[4]


def test_refused_confirmation_writes_nothing(tmp_path, monkeypatch):
    out = tmp_path / "contract.json"
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    with pytest.raises(SystemExit):
        main(["confirm", "--demo", str(DEMO), "--by", "operator", "--out", str(out)])
    assert not out.exists()


def test_accepted_confirmation_writes_a_schema_valid_contract(tmp_path, monkeypatch):
    out = tmp_path / "contract.json"
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    main(["confirm", "--demo", str(DEMO), "--by", "operator", "--out", str(out)])
    assert json.loads(out.read_text())["confirmed"]["by"] == "operator"


def test_a_demo_that_changes_more_than_start_cannot_be_drafted():
    demo = json.loads(DEMO.read_text())
    demo["after"]["clinician"] = "Dr. Menon"
    with pytest.raises(ContractInvalid):
        draft_from_demo(demo)
