"""UI verifier (runtime, browser-only).

Reads the portal the way a careful person would, and never through the actor's row position or
element handles: every read is a fresh navigation. The detail page reached through search is
authoritative. Frozen timing: poll every 1 s for up to 8 s.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import Page

from flightdeck.contract import short
from flightdeck.receipt_rules import CHANGE_CLAIM

POLL_INTERVAL_S = 1.0
POLL_TIMEOUT_S = 8.0
LABELS = {"ID": "displayed_id", "Patient": "patient", "Clinician": "clinician", "Start": "start",
          "Duration": "duration_min", "Status": "status"}

DETAIL_JS = """() => {
  const out = {};
  for (const dt of document.querySelectorAll('dl dt')) {
    const dd = dt.nextElementSibling;
    if (!dd) continue;
    const t = dd.querySelector('time');
    out[dt.textContent.trim()] = t ? t.getAttribute('datetime') : dd.textContent.trim();
  }
  return out;
}"""
DAY_ROWS_JS = """() => [...document.querySelectorAll('tbody tr')].map(r => ({
  start: r.querySelector('time') ? r.querySelector('time').getAttribute('datetime') : null,
  id: r.querySelector('td.appt-id') ? r.querySelector('td.appt-id').textContent.trim() : null,
  status: r.cells.length ? r.cells[r.cells.length - 1].textContent.trim() : null }))"""
LIST_ROWS_JS = """(sel) => [...document.querySelectorAll(sel)].map(r => ({
  id: r.querySelector('td.appt-id') ? r.querySelector('td.appt-id').textContent.trim() : null,
  start: r.querySelector('time') ? r.querySelector('time').getAttribute('datetime') : null }))"""


class Evidence:
    """Screenshots under runs/<hex>/; returns the path string used in the receipt."""

    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def shot(self, page: Page, name: str) -> str:
        path = self.dir / f"{name}.png"
        page.screenshot(path=str(path), full_page=True)
        return str(path)


# ---- Readers --------------------------------------------------------------------------------

def read_record(page: Page, base: str, appt_id: str) -> dict:
    """Search by ID, open the detail page, return {'displayed_id', 'fields'}."""
    page.goto(f"{base}/search?id={quote(appt_id)}")
    link = page.get_by_role("link", name=appt_id, exact=True)
    if link.count() != 1:
        return {"displayed_id": None, "fields": {}}
    link.click()
    page.wait_for_load_state()
    raw = page.evaluate(DETAIL_JS)
    out: dict = {"displayed_id": raw.get("ID"), "fields": {}}
    for label, key in LABELS.items():
        if key == "displayed_id" or label not in raw:
            continue
        value = raw[label]
        if key == "duration_min":
            m = re.match(r"\s*(\d+)", value)
            if not m:
                continue
            value = int(m.group(1))
        out["fields"][key] = value
    return out


def read_slot(page: Page, base: str, clinician: str | None, iso: str) -> list[str] | None:
    """Booked occupants of (clinician, start) from the clinician's day view; None if unreadable."""
    if not clinician:
        return None
    page.goto(f"{base}/day")
    select = page.get_by_label("Clinician")
    if select.count() != 1 or clinician not in select.locator("option").all_inner_texts():
        return None
    select.select_option(label=clinician)
    page.get_by_label("Date").fill(iso[:10])
    page.get_by_role("button", name="Show").click()
    page.wait_for_load_state()
    rows = page.evaluate(DAY_ROWS_JS)
    return sorted(r["id"] for r in rows if r["start"] == iso and r["status"] == "booked" and r["id"])


def record_result(expected: dict, read: dict, subject: str, fields: list[str]) -> tuple[str, dict]:
    if read["displayed_id"] != subject:
        return "unreadable", {}
    obs = {f: read["fields"][f] for f in fields if f in read["fields"]}
    differs = [f for f in fields if f in obs and obs[f] != expected.get(f)]
    missing = [f for f in fields if f not in obs]
    if differs:
        return "fail", obs
    if missing:
        return "unreadable", obs
    return "pass", obs


# ---- Pre-flight ---------------------------------------------------------------------------

@dataclass
class Preflight:
    target: dict
    resolved_ids: list[str]
    snapshot_evidence: str
    list_starts: dict[str, str]
    at_risk: dict[str, dict]
    at_risk_evidence: dict[str, str]
    clinician: str | None
    dest_before: list[str] | None
    origin_before: list[str] | None
    evidence: dict[str, str] = field(default_factory=dict)


def preflight(page: Page, base: str, contract: dict, script: dict, ev: Evidence) -> Preflight:
    target = contract["target"]["id"]
    ch = contract["change"][0]
    t = read_record(page, base, target)
    t_ev = ev.shot(page, f"pre-detail-{target}")

    # Collateral snapshot: run every recorded row locator on the pre-action page.
    list_path = next(s["path"] for s in script["steps"] if s["action"] == "goto")
    page.goto(base + list_path)
    resolved: list[str] = []
    row_selector = "table tbody tr"
    for step in script["steps"]:
        if "row" not in step:
            continue
        row_selector = step["row"]["selector"]
        row = page.locator(row_selector).nth(step["row"]["index"])
        anchor = step.get("anchor", {}).get("selector", "td.appt-id")
        if row.count() and row.locator(anchor).count():
            resolved.append(row.locator(anchor).inner_text().strip())
    list_starts = {r["id"]: r["start"] for r in page.evaluate(LIST_ROWS_JS, row_selector) if r["id"]}
    snap_ev = ev.shot(page, "pre-action-list")

    at_risk, at_risk_ev = {}, {}
    for rid in dict.fromkeys(resolved):
        if rid != target:
            at_risk[rid] = read_record(page, base, rid)
            at_risk_ev[rid] = ev.shot(page, f"pre-detail-{rid}")

    clinician = t["fields"].get("clinician")
    dest = read_slot(page, base, clinician, ch["to"])
    dest_ev = ev.shot(page, "pre-day-destination")
    origin = read_slot(page, base, clinician, ch["from"])
    return Preflight(target=t, resolved_ids=resolved, snapshot_evidence=snap_ev, list_starts=list_starts,
                     at_risk=at_risk, at_risk_evidence=at_risk_ev, clinician=clinician,
                     dest_before=dest, origin_before=origin,
                     evidence={"target": t_ev, "destination": dest_ev})


# ---- Post-action verification -------------------------------------------------------------

def _fmt(fieldname: str, value) -> str:
    return short(value) if fieldname == "start" and isinstance(value, str) else str(value)


def _slot_check(kind, subject, expected, before, observed, reads_ev) -> dict:
    obs: dict = {"occupants_before_action": before} if before is not None else {}
    if observed is None:
        result = "unreadable"
    else:
        obs["occupants"] = observed
        result = "pass" if set(observed) == set(expected) else "fail"
    return {"check": kind, "subject": subject, "via": "day_view", "displayed_id": None,
            "expected": {"occupants": sorted(expected)}, "observed": obs, "result": result,
            "reads": 1, "evidence": reads_ev}


def verify(page: Page, base: str, contract: dict, pre: Preflight, wrote: bool, ev: Evidence,
           poll_interval: float = POLL_INTERVAL_S, poll_timeout: float = POLL_TIMEOUT_S) -> dict:
    target = contract["target"]["id"]
    ch = contract["change"][0]
    fields = ["start"] + list(contract["preserve"])
    want_start = ch["to"] if wrote else ch["from"]
    expected = {"start": want_start}
    expected.update({f: pre.target["fields"][f] for f in contract["preserve"] if f in pre.target["fields"]})

    # Target: fresh search -> detail every second, up to 8 s, stop on a match.
    reads, t0 = 0, time.monotonic()
    while True:
        read = read_record(page, base, target)
        reads += 1
        result, observed = record_result(expected, read, target, fields)
        if result == "pass" or reads * poll_interval >= poll_timeout:
            break
        time.sleep(max(0.0, t0 + reads * poll_interval - time.monotonic()))
    target_ev = ev.shot(page, f"verify-target-read{reads}")
    checks = [{"check": "target", "subject": target, "via": "search_detail",
               "displayed_id": read["displayed_id"], "expected": expected, "observed": observed,
               "result": result, "reads": reads, "evidence": [target_ev]}]

    # Collateral: snapshot of what the recorded locators hit, then a fresh read of each.
    checks.append({"check": "collateral_candidates",
                   "subject": "IDs the recorded locators resolved to before the click",
                   "via": "pre_action_snapshot", "displayed_id": None, "expected": {},
                   "observed": {"resolved_ids": pre.resolved_ids}, "result": "pass", "reads": 1,
                   "evidence": [pre.snapshot_evidence]})
    affected: dict[str, dict] = {}
    for rid, before in pre.at_risk.items():
        post = read_record(page, base, rid)
        post_ev = ev.shot(page, f"post-detail-{rid}")
        res, obs = record_result(before["fields"], post, rid, fields)
        checks.append({"check": "collateral_candidates", "subject": rid, "via": "search_detail",
                       "displayed_id": post["displayed_id"], "expected": dict(before["fields"]),
                       "observed": obs, "result": res, "reads": 1,
                       "evidence": [pre.at_risk_evidence[rid], post_ev]})
        if res == "fail":
            diffs = [f for f in fields if f in obs and obs[f] != before["fields"].get(f)]
            affected[rid] = {
                "id": rid,
                "change_observed": "; ".join(f"{f} {_fmt(f, before['fields'].get(f))} -> {_fmt(f, obs[f])}"
                                             for f in diffs),
                "evidence": [f"{pre.snapshot_evidence} (recorded locator resolved to {rid} before the click)",
                             f"{post_ev} (detail page displays ID {rid}, "
                             + ", ".join(f"{f} {_fmt(f, obs[f])}" for f in diffs) + ")"]}

    # Slots: destination and origin, from the clinician's day view.
    dest_subject = f"{pre.clinician or 'clinician'}, {short(ch['to'])}"
    origin_subject = f"{pre.clinician or 'clinician'}, {short(ch['from'])}"
    dest_before = pre.dest_before or []
    origin_before = pre.origin_before or []
    if wrote:
        dest_exp = set(dest_before) | {target}
        origin_exp = set(origin_before) - {target}
    else:
        dest_exp = set(dest_before) - {target}
        origin_exp = set(origin_before) | {target}
    dest_post = read_slot(page, base, pre.clinician, ch["to"])
    dest_ev = ev.shot(page, "post-day-destination")
    origin_post = read_slot(page, base, pre.clinician, ch["from"])
    origin_ev = ev.shot(page, "post-day-origin")
    checks.append(_slot_check("destination_slot", dest_subject, dest_exp, pre.dest_before, dest_post,
                              [pre.evidence["destination"], dest_ev]))
    checks.append(_slot_check("origin_slot", origin_subject, origin_exp, pre.origin_before, origin_post,
                              [origin_ev]))

    # A record that appeared in the destination slot gets its own detail read before it is named.
    for rid in dest_post or []:
        if rid == target or rid in dest_before or rid in affected:
            continue
        post = read_record(page, base, rid)
        post_ev = ev.shot(page, f"post-detail-{rid}")
        if post["displayed_id"] != rid:
            continue
        now = post["fields"].get("start")
        if rid in pre.list_starts and now:
            change = f"start {short(pre.list_starts[rid])} -> {short(now)}"
            listed = f"{pre.snapshot_evidence} (row shows {rid} at {short(pre.list_starts[rid])})"
        else:
            change = f"now in {dest_subject} (not there before the action)"
            listed = f"{pre.evidence['destination']} ({rid} not in the slot before the action)"
        affected[rid] = {"id": rid, "change_observed": change, "evidence": [
            listed,
            f"{dest_ev} ({rid} in the {short(ch['to'])} slot, "
            + ("empty" if not dest_before else "not there") + " before the action)",
            f"{post_ev} (detail page displays ID {rid}, start {short(now) if now else 'unreadable'})"]}

    return {"checks": checks, "affected": list(affected.values()), "target_reads": reads,
            "target_observed": observed, "target_result": result,
            "poll_seconds": round(reads * poll_interval)}
