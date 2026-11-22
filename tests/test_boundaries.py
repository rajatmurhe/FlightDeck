"""The runtime (flightdeck/) must never import the evaluator side (harness/)."""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_runtime_never_imports_harness():
    offenders = []
    for path in (ROOT / "flightdeck").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            offenders += [f"{path.relative_to(ROOT)} imports {n}" for n in names if n.split(".")[0] == "harness"]
    assert offenders == []
