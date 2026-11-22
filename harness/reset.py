"""One-command reset (evaluator side).

pristine.db is built once per (design, seed) and never rebuilt on reset, because audit
timestamps would change the bytes. Reset copies pristine.db over live.db.

CLI: python -m harness.reset C0 1 [--workdir DIR] [--rebuild]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from harness.fixtures import make_fixture

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "schema.sql"
DEFAULT_WORKDIR = HERE / "state"


@dataclass(frozen=True)
class ResetPaths:
    pristine: Path
    live: Path
    fixture: Path
    flags: Path


class StalePristineError(RuntimeError):
    pass


def _build_pristine(fx: dict, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(SCHEMA.read_text())
        con.executemany("INSERT INTO clinicians (id, name) VALUES (?, ?)",
                        [(c["id"], c["name"]) for c in fx["clinicians"]])
        con.executemany("INSERT INTO patients (id, name) VALUES (?, ?)",
                        [(p["id"], p["name"]) for p in fx["patients"]])
        con.executemany(
            "INSERT INTO appointments (id, patient_id, clinician_id, start, duration_min, status, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(r["id"], r["patient_id"], r["clinician_id"], r["start"], r["duration_min"], r["status"],
              r["updated_at"]) for r in fx["rows"]])
        con.execute("DELETE FROM audit_log")
        con.execute("DELETE FROM sqlite_sequence WHERE name = 'audit_log'")
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()
    os.replace(tmp, dest)


def reset(design: str, seed: int, workdir: str | os.PathLike | None = None,
          rebuild: bool = False) -> ResetPaths:
    base = Path(workdir) if workdir is not None else DEFAULT_WORKDIR
    d = base / f"{design}-s{seed}"
    d.mkdir(parents=True, exist_ok=True)
    paths = ResetPaths(pristine=d / "pristine.db", live=d / "live.db", fixture=d / "fixture.json",
                       flags=d / "flags.json")

    fx = make_fixture(design, seed)
    if rebuild or not paths.pristine.exists():
        _build_pristine(fx, paths.pristine)
        paths.fixture.write_text(json.dumps(fx, indent=2, sort_keys=True))
    elif not paths.fixture.exists() or json.loads(paths.fixture.read_text()) != fx:
        raise StalePristineError(
            f"{paths.pristine} was built from a different fixture; pass rebuild=True / --rebuild")

    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(paths.live) + suffix).unlink(missing_ok=True)
    shutil.copyfile(paths.pristine, paths.live)
    # Portal fault flags live next to the DB. Only the portal process is given this path.
    paths.flags.write_text(json.dumps({"flags": fx["faults"].get("portal_flags", {})}, sort_keys=True))
    return paths


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m harness.reset", description=__doc__.splitlines()[0])
    ap.add_argument("design")
    ap.add_argument("seed", type=int)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args(argv)
    p = reset(args.design, args.seed, workdir=args.workdir, rebuild=args.rebuild)
    print(f"pristine  {p.pristine}")
    print(f"live      {p.live}")
    print(f"live sha  {sha256(p.live)}")


if __name__ == "__main__":
    main()
