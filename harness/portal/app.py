"""Synthetic clinic portal (evaluator side). FlightDeck only ever sees its HTML.

Server-rendered, no JS framework. Every list row carries its own form with a hidden
appointment ID. Double-booking is deliberately allowed.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

IST = timezone(timedelta(hours=5, minutes=30))
KNOWN_FLAGS: set[str] = set()   # Day 3+: S1 miswrite, Day 5: I1 / B1
NEW_START = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

APPT_SQL = """
SELECT a.id, a.start, a.duration_min, a.status, a.updated_at,
       a.clinician_id, c.name AS clinician, a.patient_id, p.name AS patient
FROM appointments a
JOIN clinicians c ON c.id = a.clinician_id
JOIN patients p ON p.id = a.patient_id
"""


def pretty(iso: str) -> str:
    """'2026-12-15T16:00:00+05:30' -> 'Tue 15 Dec 2026 16:00'."""
    return datetime.fromisoformat(iso).strftime("%a %d %b %Y %H:%M")


TEMPLATES.env.filters["pretty"] = pretty


class UnknownFlagError(ValueError):
    pass


def load_flags(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    flags = json.loads(path.read_text()).get("flags", {})
    unknown = set(flags) - KNOWN_FLAGS
    if unknown:
        raise UnknownFlagError(f"unknown fault flags: {sorted(unknown)}")
    return flags


def create_app(db_path: str | Path, flags_path: str | Path | None = None) -> FastAPI:
    db = Path(db_path)
    flags_file = Path(flags_path) if flags_path else None
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def connect() -> sqlite3.Connection:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    def query(sql: str, args: tuple = ()) -> list[dict]:
        with closing(connect()) as con:
            return [dict(r) for r in con.execute(sql, args)]

    def get_appt(appt_id: str) -> dict | None:
        rows = query(APPT_SQL + " WHERE a.id = ?", (appt_id,))
        return rows[0] if rows else None

    def render(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
        ctx["flags"] = load_flags(flags_file)   # re-read every request
        return TEMPLATES.TemplateResponse(request, name, ctx, status_code=status)

    def not_found(request: Request, what: str) -> HTMLResponse:
        return render(request, "not_found.html", status=404, what=what)

    @app.get("/")
    def home():
        return RedirectResponse("/appointments", status_code=303)

    @app.get("/appointments", response_class=HTMLResponse)
    def list_page(request: Request, msg: str | None = None):
        rows = query(APPT_SQL + " ORDER BY a.start, a.id")
        return render(request, "list.html", rows=rows, updated=(msg == "updated"))

    @app.get("/appointments/{appt_id}", response_class=HTMLResponse)
    def detail(request: Request, appt_id: str):
        appt = get_appt(appt_id)
        if appt is None:
            return not_found(request, f"Appointment {appt_id}")
        return render(request, "detail.html", a=appt)

    @app.get("/search", response_class=HTMLResponse)
    def search(request: Request, id: str | None = None):
        q = (id or "").strip()
        appt = get_appt(q) if q else None
        return render(request, "search.html", q=q, a=appt)

    @app.get("/day", response_class=HTMLResponse)
    def day(request: Request, clinician: str | None = None, date: str | None = None):
        clinicians = query("SELECT id, name FROM clinicians ORDER BY name")
        rows, name = [], None
        if clinician and date:
            name = next((c["name"] for c in clinicians if c["id"] == clinician), None)
            rows = query(APPT_SQL + " WHERE a.clinician_id = ? AND substr(a.start, 1, 10) = ?"
                         " ORDER BY a.start, a.id", (clinician, date))
        return render(request, "day.html", clinicians=clinicians, clinician=clinician,
                      clinician_name=name, date=date, rows=rows)

    @app.get("/reschedule", response_class=HTMLResponse)
    def reschedule_form(request: Request, appointment_id: str):
        appt = get_appt(appointment_id)
        if appt is None:
            return not_found(request, f"Appointment {appointment_id}")
        return render(request, "reschedule.html", a=appt, error=None)

    @app.post("/reschedule", response_class=HTMLResponse)
    def reschedule(request: Request, appointment_id: str = Form(...), new_start: str = Form("")):
        appt = get_appt(appointment_id)
        if appt is None:
            return not_found(request, f"Appointment {appointment_id}")
        if not NEW_START.match(new_start):
            return render(request, "reschedule.html", status=400, a=appt,
                          error="Enter a date and time.")
        start = datetime.fromisoformat(new_start).replace(tzinfo=IST).isoformat()
        now = datetime.now(IST).isoformat(timespec="seconds")
        # Deliberately no slot-conflict check: double-booking is possible.
        with closing(connect()) as con, con:
            con.execute("UPDATE appointments SET start = ?, updated_at = ? WHERE id = ?",
                        (start, now, appointment_id))
            con.execute("INSERT INTO notifications (appt_id, kind, at) VALUES (?, 'rescheduled', ?)",
                        (appointment_id, now))
        return RedirectResponse("/appointments?msg=updated", status_code=303)

    return app
