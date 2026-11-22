"""Start the portal in a background thread on a free local port (tests and, later, the runner)."""
from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import uvicorn

from harness.portal.app import create_app


@contextmanager
def running(db: str | Path, flags: str | Path | None = None, timeout: float = 10.0) -> Iterator[str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(db, flags), host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + timeout
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("portal did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
