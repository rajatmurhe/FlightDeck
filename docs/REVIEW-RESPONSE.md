# Response to review: v0.1 to v0.2

**Reviewer's verdict:** approve the two-week pilot. Before the model repair loop is built, make sure
a receipt cannot say `verified_within_scope` unless the target appointment was read back after the action.

## 1. Every finding was reproduced on v0.1 first

| Finding | Reproduction on v0.1 | Status |
| --- | --- | --- |
| S1 receipt reduced to the passing pre-action snapshot, verdict set to `verified_within_scope` | Schema errors: none. Verdict formula: `verified_within_scope` | Confirmed |
| `refused_no_change` together with `writes_submitted: 1` | Schema errors: none | Confirmed |
| Validator exit code | Without `rfc3339-validator`: printed `non RFC3339 time: WRONGLY ACCEPTED`, exit code 0 | Confirmed |
| Receipt ID `rcpt-S1-seed0-A1` names the fault design | Visible in the example | Confirmed |

## 2. What changed

| Area | v0.2 change | Files |
| --- | --- | --- |
| Evidence rules | `validate_receipt(contract, receipt)` works out the required checks from the frozen contract. It requires a post-action readback of the target through search or its detail page, showing the requested ID and every contract field. It also reconciles outcome, write count and claim, requires a post-action read of every row that was at risk before the click, and recomputes the verdict. `seal()` refuses any receipt with a violation and writes nothing to the run log | `flightdeck/receipt_rules.py` |
| Receipt shape | Schema 0.2 ties outcome, write count and claim together. A pre-action snapshot may only list at-risk rows and cannot fail. Run and receipt IDs must be opaque (`run-` or `rcpt-` plus 8 or more hex characters) | `schemas/verifier-receipt.schema.json` |
| Tests | 30 pytest tests replace the print-only script, and the suite fails if RFC 3339 checking is unavailable. `tools/validate_examples.py` now exits with pytest's code: 1 without `rfc3339-validator`, 0 with it (both checked) | `tests/`, `tools/validate_examples.py`, `requirements.txt` |
| Examples | S1 uses opaque IDs and a snapshot with no expectations of its own. New refusal example O1 shows the `no_change` claim | `examples/` |
| Leakage | The executor, repair prompt and cache see only opaque run IDs. The scorer joins in design and seed after sealing. This is added to the Day 8 leak tests | Plan: Fixtures, Day 8 |
| Baseline fairness | A1's ladder gains a generic menu step: open an accessible menu in the anchored row and look for the recorded action. If that solves K2, it counts as a rules win | Plan: Arms, Day 6 |
| Labels | The fixture table freezes only each fixture's correct outcome, plus "fixture checks" saying what naive replay must do. Arm predictions are removed | Plan: Fixtures |
| Decision rule | The 3/n bound is removed. Rule 2 now also requires zero in-scope false approvals. The result is described as a decision about the next week, not a failure-rate estimate | Plan: Metrics |
| Time | Fixtures are grouped as Core (C0, R1, O1, O2, I1, S1, B1), Repair (K0 to K2) and Tier 2 (cut first). A Day-5 checkpoint sends week 2 to verification if the core is unreliable | Plan: Fixtures, Day-by-day |

## 3. The reviewer's Day-1 acceptance pair

Both tests are in `tests/test_receipt_rules.py` and pass.

- `test_s1_without_post_action_evidence_cannot_be_sealed_as_verified`: the stripped receipt still fools
  the bare verdict formula, but `seal()` raises `ReceiptRejected` and writes no log line. Its violations are:
  - scope requires a check of kind 'target' and none is present
  - scope requires a check of kind 'destination_slot' and none is present
  - scope requires a check of kind 'origin_slot' and none is present
  - no post-action readback of A-104 through search or its detail page
- `test_intact_s1_seals_as_observed_mismatch`: the full S1 receipt seals, and its verdict is `observed_mismatch`.

## 4. Still open

- The runtime and evaluator separation can only be tested once the runner exists (Day 8).
- The browser verifier and repair engine are not built yet. The receipts are hand-written examples of what they must produce.
