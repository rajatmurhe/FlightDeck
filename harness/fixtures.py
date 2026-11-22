"""Fixture generator (evaluator side). FlightDeck never imports this module.

make_fixture(design, seed) returns the request plus the rows that seed the hidden DB.
Seed 0 is the canonical A-104 data; other seeds draw IDs, names and a week offset.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
UPDATED_AT = "2026-11-20T09:00:00+05:30"   # fixed, so seeding is byte-deterministic
BUILT_DESIGNS = {"C0"}

# Synthetic names only. Never real patient data.
PATIENT_NAMES = [
    "Asha N.", "Ravi K.", "Meena P.", "Arjun S.", "Divya R.", "Kiran M.", "Lakshmi V.",
    "Nikhil T.", "Priya D.", "Rohan B.", "Sneha G.", "Tarun J.", "Uma L.", "Vikram H.",
    "Anita C.", "Deepak W.", "Farah Q.", "Gopal Y.", "Isha Z.", "Manoj E.",
]
CLINICIAN_NAMES = [
    "Dr. Rao", "Dr. Menon", "Dr. Iyer", "Dr. Kapoor", "Dr. Nair", "Dr. Bose",
    "Dr. Pillai", "Dr. Shah", "Dr. Verma", "Dr. Das",
]

# Canonical week: Tue 15 Dec 2026 is the target day.
BASE_TUE = datetime(2026, 12, 15, tzinfo=IST)


def _at(day: datetime, days: int, hour: int, minute: int = 0) -> str:
    return (day + timedelta(days=days)).replace(hour=hour, minute=minute).isoformat()


def _row(appt_id: str, patient: tuple[str, str], clinician: tuple[str, str], start: str) -> dict:
    return {
        "id": appt_id,
        "patient_id": patient[0], "patient": patient[1],
        "clinician_id": clinician[0], "clinician": clinician[1],
        "start": start, "duration_min": 30, "status": "booked", "updated_at": UPDATED_AT,
    }


def _assemble(request: dict, rows: list[dict]) -> dict:
    clinicians = sorted({(r["clinician_id"], r["clinician"]) for r in rows})
    patients = sorted({(r["patient_id"], r["patient"]) for r in rows})
    return {
        "request": request,
        "clinicians": [{"id": i, "name": n} for i, n in clinicians],
        "patients": [{"id": i, "name": n} for i, n in patients],
        "rows": rows,
    }


def _canonical() -> dict:
    rao, menon = ("C-1", "Dr. Rao"), ("C-2", "Dr. Menon")
    rows = [
        _row("A-104", ("P-31", "Asha N."), rao, _at(BASE_TUE, 0, 16)),
        _row("A-105", ("P-32", "Ravi K."), rao, _at(BASE_TUE, 0, 16, 30)),
        _row("A-106", ("P-33", "Meena P."), menon, _at(BASE_TUE, 3, 10)),
    ]
    request = {"target_id": "A-104", "from": rows[0]["start"],
               "to": _at(BASE_TUE, 2, 11), "clinician": "Dr. Rao"}
    return _assemble(request, rows)


def _seeded(design: str, seed: int) -> dict:
    rng = random.Random(f"{design}:{seed}")
    tue = BASE_TUE + timedelta(weeks=rng.randint(0, 6))
    n_fillers = rng.randint(1, 3)
    ids = [f"A-{n}" for n in rng.sample(range(100, 1000), 3 + n_fillers)]
    names = rng.sample(PATIENT_NAMES, 3 + n_fillers)
    patients = [(f"P-{n}", name) for n, name in zip(rng.sample(range(10, 100), len(names)), names)]
    doc, other = [(f"C-{i + 1}", n) for i, n in enumerate(rng.sample(CLINICIAN_NAMES, 2))]

    hour = rng.choice([9, 10, 14, 15, 16])
    target = _row(ids[0], patients[0], doc, _at(tue, 0, hour))
    request = {"target_id": ids[0], "from": target["start"],
               "to": _at(tue, 2, rng.choice([9, 10, 11, 14, 15])), "clinician": doc[1]}
    rows = [
        target,
        _row(ids[1], patients[1], doc, _at(tue, 0, hour, 30)),          # decoy: same clinician, next slot
        _row(ids[2], patients[2], other, _at(tue, 3, rng.choice([9, 10, 11]))),  # out of scope
    ]
    taken = {(r["clinician_id"], r["start"]) for r in rows} | {(doc[0], request["to"])}
    for appt_id, patient in zip(ids[3:], patients[3:]):
        while True:
            clin = rng.choice([doc, other])
            start = _at(tue, rng.choice([0, 1, 2, 3]), rng.choice([9, 10, 11, 12, 14, 15, 16, 17]),
                        rng.choice([0, 30]))
            # Never the destination slot, never a duplicate, and always after the decoy,
            # so the target keeps row 1 and the decoy row 2 in the start-ordered list.
            if (clin[0], start) not in taken and start > rows[1]["start"]:
                taken.add((clin[0], start))
                rows.append(_row(appt_id, patient, clin, start))
                break
    return _assemble(request, rows)


def make_fixture(design: str, seed: int) -> dict:
    if design not in BUILT_DESIGNS:
        raise ValueError(f"design {design!r} not built yet")
    return _canonical() if seed == 0 else _seeded(design, seed)
