"""Day-2 gate: the portal, driven through a real browser (evaluator side)."""
import json
import socket
import sqlite3
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from harness.fixtures import make_fixture
from harness.portal import create_app
from harness.portal.app import UnknownFlagError, load_flags
from harness.reset import reset
from harness.score import score


@contextmanager
def serve(db_path, flags_path=None):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(db_path, flags_path), host="127.0.0.1",
                                           port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("portal did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def portal(tmp_path_factory):
    """Portal on C0 seed 1. Each test resets live.db; the portal opens a connection per request."""
    workdir = tmp_path_factory.mktemp("state")
    db = reset("C0", seed=1, workdir=workdir)
    with serve(db.live) as url:
        yield {"url": url, "workdir": workdir}


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


def fresh(portal):
    return reset("C0", seed=1, workdir=portal["workdir"]), make_fixture("C0", seed=1)


def reschedule_by_hand(page, base, target_id, new_start_iso):
    page.goto(f"{base}/appointments")
    row = page.locator("tbody tr").filter(has=page.locator("td.appt-id", has_text=target_id))
    assert row.count() == 1
    row.get_by_role("button", name="Reschedule").click()
    page.fill("#new_start", new_start_iso[:16])
    page.get_by_role("button", name="Save").click()
    assert page.get_by_role("status").inner_text() == "Appointment updated"


# ---- Gate ----------------------------------------------------------------------------------

def test_rescheduling_target_by_hand_scores_as_correct(portal, page):
    db, fx = fresh(portal)
    req = fx["request"]
    reschedule_by_hand(page, portal["url"], req["target_id"], req["to"])

    page.goto(f"{portal['url']}/appointments/{req['target_id']}")
    assert page.locator("dd time").first.get_attribute("datetime") == req["to"]

    report = score(db.pristine, db.live)
    assert report["changed_rows"] == [{"id": req["target_id"], "fields": ["start"],
                                       "before": {"start": req["from"]}, "after": {"start": req["to"]}}]
    assert report["audit_updates"] == 1
    assert report["inserted"] == [] and report["deleted"] == []
    assert report["notifications_added"] == [{"appt_id": req["target_id"], "kind": "rescheduled"}]


def test_double_booking_is_possible(portal, page):
    db, fx = fresh(portal)
    target, decoy = fx["rows"][0], fx["rows"][1]
    reschedule_by_hand(page, portal["url"], target["id"], decoy["start"])

    with sqlite3.connect(db.live) as con:
        ids = [r[0] for r in con.execute(
            "SELECT id FROM appointments WHERE clinician_id = ? AND start = ? AND status = 'booked'"
            " ORDER BY id", (target["clinician_id"], decoy["start"]))]
    assert ids == sorted([target["id"], decoy["id"]])


# ---- Supporting behaviour ------------------------------------------------------------------

def test_every_row_has_its_own_form_with_its_own_id(portal, page):
    _, fx = fresh(portal)
    page.goto(f"{portal['url']}/appointments")
    rows = page.locator("tbody tr")
    assert rows.count() == len(fx["rows"])
    for i in range(rows.count()):
        row = rows.nth(i)
        assert row.locator("form").count() == 1
        hidden = row.locator("form input[type=hidden][name=appointment_id]").get_attribute("value")
        assert hidden == row.locator("td.appt-id").inner_text()


def test_target_is_row_one_on_every_seed(tmp_path, page):
    for seed in range(4):
        db = reset("C0", seed=seed, workdir=tmp_path)
        with serve(db.live) as url:
            page.goto(f"{url}/appointments")
            first = page.locator("tbody tr").first.locator("td.appt-id").inner_text()
        assert first == make_fixture("C0", seed)["request"]["target_id"], seed


def test_search_detail_and_day_view_show_the_target(portal, page):
    _, fx = fresh(portal)
    req, target = fx["request"], fx["rows"][0]
    base = portal["url"]

    page.goto(f"{base}/search?id={req['target_id']}")
    assert page.locator("tbody td.appt-id").inner_text() == req["target_id"]

    page.goto(f"{base}/appointments/{req['target_id']}")
    assert page.locator("dd.appt-id").inner_text() == req["target_id"]
    assert req["clinician"] in page.locator("dl").inner_text()

    page.goto(f"{base}/day?clinician={target['clinician_id']}&date={req['from'][:10]}")
    assert req["target_id"] in page.locator("tbody td.appt-id").all_inner_texts()
    page.goto(f"{base}/day?clinician={target['clinician_id']}&date={req['to'][:10]}")
    assert page.get_by_text("No appointments").count() == 1   # C0: destination is free


def test_unknown_id_is_not_found(portal, page):
    fresh(portal)
    page.goto(f"{portal['url']}/search?id=A-0")
    assert page.get_by_text("No appointment with that ID").count() == 1
    assert page.goto(f"{portal['url']}/appointments/A-0").status == 404


def test_unknown_fault_flag_is_rejected(tmp_path):
    flags = tmp_path / "flags.json"
    assert load_flags(flags) == {}            # missing file means no flags
    flags.write_text(json.dumps({"flags": {"typo_flag": True}}))
    with pytest.raises(UnknownFlagError):
        load_flags(flags)
