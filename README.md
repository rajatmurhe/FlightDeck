# FlightDeck

**When a portal says "Appointment updated", how do we know it updated the right appointment?**

FlightDeck is a browser workflow verifier. It has browser access only and must:

- prevent a wrong write,
- catch a silent backend miswrite,
- refuse when the requested slot is taken.

A hidden scorer that reads the database judges each run after FlightDeck seals its receipt.
The pilot also measures whether model-proposed repairs beat a rules-only baseline without accepting bad repairs.

Status: two-week pilot, plan v0.2, approved by an external reviewer. See `docs/plan.md`.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && python -m playwright install chromium
python -m pytest -q
```

