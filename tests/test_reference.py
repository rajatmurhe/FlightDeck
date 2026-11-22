"""Every fixable fixture's frozen reference action works through the UI on a dev seed."""
import pytest
from playwright.sync_api import sync_playwright

from harness.judge import load_labels
from harness.reference import REFERENCE_CLICKS, run_reference


def test_reference_actions_cover_every_fixable_design():
    assert set(REFERENCE_CLICKS) == {d for d, e in load_labels().items() if e["label"] == "fixable"}


def test_every_reference_action_succeeds(tmp_path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        results = [run_reference(d, 1, browser, tmp_path) for d in REFERENCE_CLICKS]
        browser.close()
    assert [r["design"] for r in results if not r["ok"]] == []
