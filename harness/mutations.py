"""Harness-owned browser mutations (evaluator side).

Installed on the Playwright browser context before it is handed to the executor, so FlightDeck
sees only the mutated page. Scripts leave no marker: no attributes, classes, comments or globals.
"""
from __future__ import annotations

# R1: swap the first two rows of the appointment list (target row 1 <-> decoy row 2).
SWAP_FIRST_TWO_ROWS = """
(() => {
  const swap = () => {
    if (location.pathname !== '/appointments') return;
    const body = document.querySelector('table tbody');
    if (!body || body.rows.length < 2) return;
    body.insertBefore(body.rows[1], body.rows[0]);
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', swap, { once: true });
  } else {
    swap();
  }
})();
"""

SCRIPTS = {"swap_first_two_rows": SWAP_FIRST_TWO_ROWS}


def install(context, fixture: dict) -> None:
    """Add the fixture's browser mutation (if any) to a Playwright BrowserContext."""
    name = fixture.get("faults", {}).get("browser_mutation")
    if name is None:
        return
    if name not in SCRIPTS:
        raise ValueError(f"unknown browser mutation {name!r}")
    context.add_init_script(SCRIPTS[name])
