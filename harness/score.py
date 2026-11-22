"""Hidden scorer, Day-1 layer: diff live.db against pristine.db (evaluator side).

Ignores updated_at (an incidental effect). Counts audited writes so the scorer can say
"moved exactly once".

CLI: python -m harness.score <pristine.db> <live.db>
"""
from __future__ import annotations

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


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.exit("usage: python -m harness.score <pristine.db> <live.db>")
    print(json.dumps(score(*args), indent=2))


if __name__ == "__main__":
    main()
