"""Pre-write checks (runtime): the contract's if-blocked rules, applied to the pre-flight read.

Run by A1 (and later A2) before any write; A0 runs none. The first rule that fires decides:
refuse_no_change -> refused_no_change, stop_and_ask -> stopped_before_write.
"""
from __future__ import annotations

from dataclasses import dataclass

from flightdeck.contract import short
from flightdeck.verifier import Preflight

OUTCOME = {"refuse_no_change": "refused_no_change", "stop_and_ask": "stopped_before_write"}


@dataclass(frozen=True)
class Decision:
    when: str
    then: str
    source: str
    reason: str

    @property
    def outcome(self) -> str:
        return OUTCOME[self.then]


def prewrite(contract: dict, pre: Preflight) -> Decision | None:
    target = contract["target"]["id"]
    ch = contract["change"][0]
    rules = {b["when"]: b for b in contract["if_blocked"]}

    def decide(when: str, reason: str) -> Decision:
        b = rules.get(when, {"then": "stop_and_ask", "source": "policy"})   # unlisted: stop, never guess
        return Decision(when, b["then"], b["source"], reason)

    if pre.target["displayed_id"] != target:
        return decide("target_not_found", f"{target} could not be found through search")
    missing = [f for f in ["start"] + list(contract["preserve"]) if f not in pre.target["fields"]]
    if missing:
        return decide("readback_unavailable", f"{target}'s detail page does not show {', '.join(missing)}")
    if pre.dest_before is None:
        return decide("readback_unavailable", f"the {short(ch['to'])} slot could not be read")
    if pre.target["fields"]["start"] != ch["from"]:
        return decide("start_state_differs",
                      f"{target} starts {short(pre.target['fields']['start'])}, not {short(ch['from'])}")
    others = [i for i in pre.dest_before if i != target]
    if others:
        return decide("destination_occupied",
                      f"{pre.clinician} already has {', '.join(others)} at {short(ch['to'])}")
    return None
