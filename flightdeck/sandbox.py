"""What a sandbox trial gets (runtime side of the sandbox API).

The harness hands FlightDeck an open_sandbox() context manager. Each call yields a fresh staging
copy with fresh inputs: a page, its base URL and a new request. Nothing else crosses over.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable

from playwright.sync_api import Page


@dataclass(frozen=True)
class SandboxSession:
    page: Page
    base_url: str
    request: dict


OpenSandbox = Callable[[], AbstractContextManager[SandboxSession]]
