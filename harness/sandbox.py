"""Sandbox API (evaluator side): fresh staging copies for repair trials, seeds 101 and up.

Each open() resets a new fixture of the same design (faults and browser mutation included) on
the next sandbox seed, starts its own portal, and yields a page, the URL and the fresh request.
FlightDeck only ever calls the closure returned by opener().
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import Browser

from flightdeck.sandbox import OpenSandbox, SandboxSession
from harness.fixtures import make_fixture
from harness.mutations import install
from harness.portal.server import running
from harness.reset import reset

FIRST_SANDBOX_SEED = 101
REQUEST_KEYS = ("target_id", "from", "to", "clinician")
PAGE_TIMEOUT_MS = 5000


class SandboxProvider:
    def __init__(self, design: str, browser: Browser, workdir: Path, first_seed: int = FIRST_SANDBOX_SEED):
        if first_seed < FIRST_SANDBOX_SEED:
            raise ValueError("sandbox seeds start at 101 (they never overlap dev or eval seeds)")
        self._design, self._browser, self._workdir = design, browser, Path(workdir)
        self._next = first_seed
        self.seeds_used: list[int] = []

    @contextmanager
    def open(self) -> Iterator[SandboxSession]:
        seed = self._next
        self._next += 1
        self.seeds_used.append(seed)
        fx = make_fixture(self._design, seed)
        db = reset(self._design, seed, workdir=self._workdir)
        with running(db.live, db.flags) as url:
            ctx = self._browser.new_context()
            install(ctx, fx)
            page = ctx.new_page()
            page.set_default_timeout(PAGE_TIMEOUT_MS)
            try:
                yield SandboxSession(page=page, base_url=url,
                                     request={k: fx["request"][k] for k in REQUEST_KEYS})
            finally:
                ctx.close()

    def opener(self) -> OpenSandbox:
        def open_sandbox():
            return self.open()
        return open_sandbox
