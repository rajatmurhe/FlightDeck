"""Run every FlightDeck contract check and exit non-zero if any fails.

Usage:  pip install -r requirements.txt
        python tools/validate_examples.py        # same as: python -m pytest -q

v0.1 of this script printed "WRONGLY ACCEPTED" and still exited 0. It now delegates
to pytest, so a failing expectation fails the process (and CI).
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    sys.exit(pytest.main(["-q", str(ROOT / "tests")]))
