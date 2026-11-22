"""Hidden scorer (evaluator side).

score(): diff live.db against pristine.db. Ignores updated_at (an incidental effect) and counts
audited writes so the scorer can say "moved exactly once".
score_run(): refuses any receipt whose digest is not in runs.log (unsealed or edited), and only
then joins design, seed and arm from the run map.

CLI: python -m harness.score <pristine.db> <live.db>
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

IGNORED_FIELDS = {"updated_at"}


def _connect_ro(path: str | os.PathLike) -> sqlite3.Connection:
    con = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _appointments(con: sqlite3.Connection) -> dict[str, dict]:
    return {r["id"]: dict(r) for r in con.execute("SELECT * FROM appointments")}


def _audit_counts(con: sqlite3.Connection) -> dict[str, int]:
    return dict(con.execute("SELECT op, COUNT(*) FROM audit_log GROUP BY op").fetchall())


def score(pristine: str | os.PathLike, live: str | os.PathLike) -> dict:
    with closing(_connect_ro(pristine)) as p, closing(_connect_ro(live)) as l:
        before, after = _appointments(p), _appointments(l)
        audit_p, audit_l = _audit_counts(p), _audit_counts(l)
        max_seq = p.execute("SELECT COALESCE(MAX(seq), 0) FROM notifications").fetchone()[0]
        notes = [dict(r) for r in l.execute(
            "SELECT appt_id, kind FROM notifications WHERE seq > ? ORDER BY seq", (max_seq,))]

    changed = []
    for appt_id in sorted(before.keys() & after.keys()):
        b, a = before[appt_id], after[appt_id]
        fields = sorted(f for f in b if f not in IGNORED_FIELDS and b[f] != a.get(f))
        if fields:
            changed.append({"id": appt_id, "fields": fields,
                            "before": {f: b[f] for f in fields},
                            "after": {f: a[f] for f in fields}})

    def delta(op: str) -> int:
        return audit_l.get(op, 0) - audit_p.get(op, 0)

    return {
        "changed_rows": changed,
        "inserted": sorted(after.keys() - before.keys()),
        "deleted": sorted(before.keys() - after.keys()),
        "audit_updates": delta("update"),
        "audit_inserts": delta("insert"),
        "audit_deletes": delta("delete"),
        "notifications_added": notes,
    }


class UnsealedReceipt(RuntimeError):
    pass


def receipt_digest(receipt: dict) -> str:
    """Same canonical form seal() hashes in flightdeck/receipt_rules.py."""
    return hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def lookup_run(run_map: str | os.PathLike, run_id: str) -> dict:
    for line in Path(run_map).read_text().splitlines():
        entry = json.loads(line)
        if entry["run_id"] == run_id:
            return entry
    raise KeyError(f"{run_id} is not in the run map")


def score_run(receipt_path: str | os.PathLike, runs_log: str | os.PathLike, run_map: str | os.PathLike,
              pristine: str | os.PathLike, live: str | os.PathLike) -> dict:
    receipt = json.loads(Path(receipt_path).read_text())
    sealed = set(Path(runs_log).read_text().splitlines()) if Path(runs_log).exists() else set()
    if f"{receipt['run_id']} {receipt_digest(receipt)}" not in sealed:
        raise UnsealedReceipt(f"{receipt_path}: digest not in {runs_log}; refusing to score")
    entry = lookup_run(run_map, receipt["run_id"])   # joined only after the seal check
    return {"run_id": receipt["run_id"], "design": entry["design"], "seed": entry["seed"],
            "arm": entry["arm"], "verdict": receipt["verdict"],
            "named": [a["id"] for a in receipt["affected_records"]],
            "db": score(pristine, live)}


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.exit("usage: python -m harness.score <pristine.db> <live.db>")
    print(json.dumps(score(*args), indent=2))


if __name__ == "__main__":
    main()
