"""A2's single model proposal (runtime).

Called only when the rules ladder failed before any write. The model sees the recorded step, the
target ID and the target row's accessibility tree, and answers in strict JSON with at most 2
clicks by accessible name inside that row (no typing, no new submits). The answer is validated
here, then trialled on a sandbox like any other candidate; only the UI verifier can accept it.

The prompt never carries a run ID, design name, seed or label. Replies are cached by
sha256(model + prompt); the cache file records only the opaque run ID that first paid for it.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from playwright.sync_api import Page

from flightdeck.executor import MAX_REPAIR_CLICKS, anchored_row
from flightdeck.ladder import row_step
from flightdeck.model_client import ModelCallFailed, ModelConfig, ModelReply, chat_json

CONTROL_RE = re.compile(r'-\s+(button|menuitem|link)\s+"((?:[^"\\]|\\.)*)"')

SYSTEM_PROMPT = """You repair one step of a recorded browser workflow on a clinic scheduling portal.
The recorded step clicked a control inside the table row of one appointment, but that control is
no longer there. Propose how to reach the same action from that row.

Rules (an answer that breaks any rule is discarded):
- At most 2 clicks, each naming a control in the given row by its exact accessible name.
- Only controls listed in the row's accessibility tree. No typing. No other rows or pages.
- Never choose a control that would itself submit a different change (for example cancel or
  delete). The workflow's own Save comes later and is not part of your answer.
- If no control in the row performs the recorded action, answer with an empty list.

Reply with one JSON object and nothing else:
{"clicks": ["<accessible name>", ...], "reason": "<one short sentence>"}"""


class Proposer(Protocol):
    model: str

    def __call__(self, system: str, user: str) -> ModelReply: ...


class LiveProposer:
    """The real model, configured from the environment (flightdeck.model_client)."""

    def __init__(self, cfg: ModelConfig):
        self._cfg = cfg
        self.model = cfg.model

    def __call__(self, system: str, user: str) -> ModelReply:
        return chat_json(self._cfg, system, user)


def row_controls(tree: str) -> set[str]:
    return {m.group(2).replace('\\"', '"') for m in CONTROL_RE.finditer(tree)}


def _later_steps(script: dict) -> list[str]:
    steps, seen = [], False
    for s in script["steps"]:
        if s is row_step(script):
            seen = True
            continue
        if seen and s["action"] == "fill":
            steps.append("fill the new start time")
        elif seen and s["action"] == "click":
            steps.append(f"click {s['role']} '{s['name']}'")
    return steps


def build_prompt(script: dict, target_id: str, row_tree: str) -> tuple[str, str]:
    step = row_step(script)
    user = json.dumps({
        "recorded_step": {"action": "click", "role": step["role"], "name": step["name"]},
        "target_id": target_id,
        "steps_after_this_click": _later_steps(script),
        "row_accessibility_tree": row_tree,
    }, indent=2)
    return SYSTEM_PROMPT, user


def parse_proposal(text: str, row_tree: str) -> tuple[list[str] | None, str]:
    """(clicks, why). clicks is None when the answer is invalid; [] means 'no safe repair'."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, "reply is not JSON"
    if not isinstance(data, dict) or set(data) != {"clicks", "reason"}:
        return None, "reply must have exactly the keys clicks and reason"
    clicks = data["clicks"]
    if not isinstance(clicks, list) or not all(isinstance(c, str) for c in clicks):
        return None, "clicks must be a list of names"
    if len(clicks) > MAX_REPAIR_CLICKS:
        return None, f"more than {MAX_REPAIR_CLICKS} clicks"
    unknown = [c for c in clicks if c not in row_controls(row_tree)]
    if unknown:
        return None, f"not controls in the target row: {unknown}"
    return clicks, str(data["reason"])[:200]


def cache_key(model: str, system: str, user: str) -> str:
    return hashlib.sha256(f"{model}\n{system}\n{user}".encode()).hexdigest()


def propose_with_model(page: Page, base_url: str, script: dict, request: dict, proposer: Proposer,
                       cache_dir: Path, run_id: str, log_dir: Path) -> dict:
    out = {"candidate": None, "model_calls": 0, "input_tokens": 0, "output_tokens": 0,
           "cost_usd": 0.0, "cached": False, "why": ""}
    step = row_step(script)
    list_path = next(s["path"] for s in script["steps"] if s["action"] == "goto")
    page.goto(base_url.rstrip("/") + list_path)   # fresh view, read only
    row = anchored_row(page, step, request["target_id"])
    if row is None:
        out["why"] = "target row not found"
        return out
    tree = row.aria_snapshot()
    system, user = build_prompt(script, request["target_id"], tree)
    key = cache_key(proposer.model, system, user)
    cache_file = Path(cache_dir) / f"{key}.json"

    if cache_file.exists():
        reply = ModelReply(**json.loads(cache_file.read_text())["reply"])
        out["cached"] = True
    else:
        out["model_calls"] = 1
        try:
            reply = proposer(system, user)
        except ModelCallFailed as exc:
            out["why"] = f"model call failed: {exc}"
            _log(log_dir, key, system, user, None, out)
            return out
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"key": key, "run_id": run_id, "reply": asdict(reply)}, indent=2))
        out.update(input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
                   cost_usd=reply.cost_usd)

    clicks, why = parse_proposal(reply.text, tree)
    out["why"] = why
    if clicks:
        out["candidate"] = {"rung": "model", "clicks": clicks}
    _log(log_dir, key, system, user, reply, out)
    return out


def _log(log_dir: Path, key: str, system: str, user: str, reply: ModelReply | None, out: dict) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    (Path(log_dir) / "model.json").write_text(json.dumps({
        "cache_key": key, "prompt": {"system": system, "user": user},
        "reply": asdict(reply) if reply else None, "result": out}, indent=2))
