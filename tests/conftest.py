import copy
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load(rel):
    return json.loads((ROOT / rel).read_text())


@pytest.fixture
def root():
    return ROOT


@pytest.fixture
def contract_schema():
    return _load("schemas/intent-contract.schema.json")


@pytest.fixture
def receipt_schema():
    return _load("schemas/verifier-receipt.schema.json")


@pytest.fixture
def contract():
    return _load("examples/contract.A-104.json")


@pytest.fixture
def s1():
    return copy.deepcopy(_load("examples/receipt.A-104.S1.json"))


@pytest.fixture
def o1():
    return copy.deepcopy(_load("examples/receipt.A-104.O1.json"))
