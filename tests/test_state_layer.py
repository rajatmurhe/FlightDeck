"""Day-1 gate: hidden state layer, reset and scorer (evaluator side)."""
import hashlib, sqlite3
from harness.fixtures import make_fixture
from harness.reset import reset          # returns an object with .pristine and .live paths
from harness.score import score


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# ---- The three tests from the Day 1 task (verbatim) -------------------------------------

def test_one_update_scores_as_one_change(tmp_path):
    fx = make_fixture("C0", seed=1)
    db = reset("C0", seed=1, workdir=tmp_path)
    with sqlite3.connect(db.live) as con:
        con.execute("UPDATE appointments SET start = ?, updated_at = 't1' WHERE id = ?",
                    (fx["request"]["to"], fx["request"]["target_id"]))
    report = score(db.pristine, db.live)
    assert [r["id"] for r in report["changed_rows"]] == [fx["request"]["target_id"]]
    assert report["changed_rows"][0]["fields"] == ["start"]   # updated_at is incidental
    assert report["audit_updates"] == 1


def test_reset_restores_identical_bytes(tmp_path):
    db = reset("C0", seed=1, workdir=tmp_path)
    first = sha(db.live)
    with sqlite3.connect(db.live) as con:
        con.execute("DELETE FROM appointments")
    assert sha(reset("C0", seed=1, workdir=tmp_path).live) == first


def test_seeds_change_ids_and_names():
    a, b = make_fixture("C0", seed=1), make_fixture("C0", seed=2)
    assert a["request"]["target_id"] != b["request"]["target_id"]
    assert a["rows"] != b["rows"]


# ---- Supporting behaviour ----------------------------------------------------------------

def test_seed_zero_is_the_canonical_a104_fixture():
    fx = make_fixture("C0", seed=0)
    assert fx["request"] == {"target_id": "A-104", "from": "2026-12-15T16:00:00+05:30",
                             "to": "2026-12-17T11:00:00+05:30", "clinician": "Dr. Rao"}
    rows = {r["id"]: (r["patient"], r["clinician"], r["start"], r["duration_min"]) for r in fx["rows"]}
    assert rows == {
        "A-104": ("Asha N.", "Dr. Rao", "2026-12-15T16:00:00+05:30", 30),
        "A-105": ("Ravi K.", "Dr. Rao", "2026-12-15T16:30:00+05:30", 30),
        "A-106": ("Meena P.", "Dr. Menon", "2026-12-18T10:00:00+05:30", 30),
    }


def test_pristine_has_an_empty_audit_log(tmp_path):
    db = reset("C0", seed=1, workdir=tmp_path)
    with sqlite3.connect(db.pristine) as con:
        assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == len(
            make_fixture("C0", seed=1)["rows"])


def test_reset_does_not_rebuild_pristine(tmp_path):
    db = reset("C0", seed=2, workdir=tmp_path)
    before = (sha(db.pristine), db.pristine.stat().st_mtime_ns)
    reset("C0", seed=2, workdir=tmp_path)
    assert (sha(db.pristine), db.pristine.stat().st_mtime_ns) == before


def test_c0_destination_slot_is_free():
    for seed in range(4):
        fx = make_fixture("C0", seed)
        req = fx["request"]
        assert not [r for r in fx["rows"] if r["clinician"] == req["clinician"] and r["start"] == req["to"]]


def test_double_booking_is_possible(tmp_path):
    fx = make_fixture("C0", seed=1)
    target = fx["rows"][0]
    db = reset("C0", seed=1, workdir=tmp_path)
    with sqlite3.connect(db.live) as con:
        con.execute("INSERT INTO appointments VALUES ('A-1000', ?, ?, ?, 30, 'booked', 't1')",
                    (fx["rows"][1]["patient_id"], target["clinician_id"], target["start"]))
    report = score(db.pristine, db.live)
    assert report["inserted"] == ["A-1000"] and report["audit_inserts"] == 1
