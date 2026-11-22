"""Frozen labels: complete, well-formed, and unchanged since tag labels-frozen (hard rule 7)."""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LABELS = ROOT / "harness" / "labels" / "labels.json"
ALL_DESIGNS = {"C0", "R1", "O1", "O2", "I1", "S1", "B1", "K0", "K1", "K2", "I2", "S2", "D1", "V1", "N1"}
SIX_LABELS = {"fixable", "should_refuse", "insufficient_evidence", "no_repair_needed", "detect_only", "out_of_scope"}
OUTCOMES = {"write_submitted", "refused_no_change", "stopped_before_write"}
VERDICTS = {"verified_within_scope", "observed_mismatch", "unable_to_verify"}


def test_every_design_has_one_of_six_labels_and_frozen_outcomes():
    designs = json.loads(LABELS.read_text())["designs"]
    assert set(designs) == ALL_DESIGNS
    for name, d in designs.items():
        assert d["label"] in SIX_LABELS, name
        assert d["correct_outcomes"], name
        for o in d["correct_outcomes"] + d.get("safe_but_manual", []):
            assert o["outcome"] in OUTCOMES and o["verdict"] in VERDICTS, name
        assert "arm" not in json.dumps(d["correct_outcomes"]), name   # no arm predictions


def test_labels_unchanged_since_freeze_tag():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("no git checkout")
    tag = subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/tags/labels-frozen"],
                         cwd=ROOT, capture_output=True)
    assert tag.returncode == 0, "tag labels-frozen is missing"
    diff = subprocess.run(["git", "diff", "--quiet", "labels-frozen", "--", "harness/labels"], cwd=ROOT)
    assert diff.returncode == 0, "harness/labels changed after the freeze"
