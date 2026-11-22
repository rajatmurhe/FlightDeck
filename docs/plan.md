# FlightDeck pilot: verifying browser writes (two-week build plan, v0.2)

Rajat Murhe · 22 Nov 2026 · Markdown copy of the plan doc. `plan.pdf` has the same content, formatted. The worked JSON examples live in `examples/` instead of being repeated here.

## Changes after external review (v0.2)

The reviewer approved the pilot on one condition, to be met before the repair loop is built: a receipt must never pass as verified unless the target was read back after the action. That is now fixed and tested.

| Finding | Change in v0.2 | Where |
| --- | --- | --- |
| A receipt holding only the pre-click snapshot passed as `verified_within_scope` | New `validate_receipt(contract, receipt)` works out the required checks from the contract, requires a post-action readback that shows A-104 and its fields, and recomputes the verdict. `seal()` refuses any receipt with a violation | `flightdeck/receipt_rules.py` |
| `refused_no_change` with `writes_submitted: 1` passed the schema | Schema 0.2 ties the outcome, write count and claim together | `schemas/verifier-receipt.schema.json` |
| The validator printed `WRONGLY ACCEPTED` and still exited 0 | pytest suite. The run fails if date-time checking is unavailable | `tests/` |
| Receipt ID `rcpt-S1-seed0-A1` revealed the fault design | Opaque run and receipt IDs, enforced by a schema pattern. The scorer joins design and seed only after sealing | Fixtures; Day 8 |
| A2 could open a menu; A1's ladder could not | A1 gets a generic menu step. If it solves K2, that counts as a rules win | Arms; Day 6 |
| The fixture table predicted which arm would succeed | The table freezes only the correct outcome | Fixtures |
| The 3/n bound overstated what 6 fixtures can show | Removed. Day 10 decides where the next week goes, nothing more | Metrics |
| 40 hours is tight | Core fixtures are protected first and Tier 2 is cut first. A Day-5 checkpoint can move week 2 to verification | Fixtures; Day plan |

## Question and scope

When the portal says "Appointment updated," can FlightDeck show from the browser alone that A-104 moved to Thu 17 Dec 11:00 with Dr. Rao, and that nothing else in its declared scope changed? Second question: do model-proposed repairs fix more cases than rules alone, without accepting a bad repair? The decision is due Fri 4 Dec, after 10 working days of about 4 focused hours each.

**The three demo outcomes**

1. **Prevent a wrong write.** The rows have been reordered. Before clicking, the guard reads A-105 in the row the recorded selector points to, so it does not click.
2. **Catch a silent failure.** The button belongs to A-104, but the backend moves A-105 and still shows "Appointment updated." A fresh lookup shows A-104 is still on Tuesday.
3. **Refuse.** Dr. Rao's Thursday 11:00 slot is taken. FlightDeck changes nothing and says why.

**Arms.** All three share the fixtures, contract, verifier, hidden scorer, a budget of 3 sandbox trials and the one-write rule.

| Arm | Executor | Repairs | Why it exists |
| --- | --- | --- | --- |
| A0 naive | Recorded script only. No ID guard, no checks before the write | None | Reference arm. It produces the real wrong writes the verifier has to catch |
| A1 rules | Recorded script + ID guard + the contract's checks before the write | Deterministic ladder, including a menu step | Baseline |
| A2 rules + model | Same as A1 | Ladder first, then one model proposal if the ladder fails before any write | Treatment |

**Canonical fixture (seed 0, synthetic, IST +05:30).** A-104: Asha N., Dr. Rao, Tue 15 Dec 2026 16:00, 30 min. A-105: Ravi K., Dr. Rao, Tue 15 Dec 16:30 (the decoy). A-106: Meena P., Dr. Menon, Fri 18 Dec 10:00 (out of scope). Fresh seeds change the IDs, names and dates. The target keeps its recorded row position in every fixture except R1.

**Not in the pilot:** Chrome extension, multi-demo alignment, pgvector, Redis, MCP, dashboard, Easy!Appointments, external healers, and requests that name a time but no appointment ID.

## Design decisions (contradictions fixed before Day 1)

1. **Labels.** Six frozen labels: `fixable`, `should_refuse`, `insufficient_evidence`, `no_repair_needed`, `detect_only`, `out_of_scope`.
2. **Guard vs repair.** The guard always blocks a click on a row whose displayed ID differs from the target. Continuing by ID counts as a repair and goes through the same sandbox trial as any other repair. R1 tests the guard; the model can only add value on changed-control faults (K family). K0 is a control change that rules can solve; if A1 fails it, the baseline is a strawman, so fix the ladder before comparing. The ladder has a generic menu step, so K2 may turn out to be a rules win.
3. **Independent faults.** Reskins of one fault count as one design. K1 (renamed button among siblings) and K2 (moved into a menu) are distinct. Report "x/6 fixtures across 2 designs."
4. **Sandbox trials.** Only the UI verifier accepts a sandbox trial, never the database or scorer. Sandbox seeds (101+) never overlap eval seeds (11 to 13). Word repair claims as "validated on a staging copy."
5. **One write.** The attempt budget applies only before the write. At most one submitted write per run. After any write, the run ends in verification.
6. **Refusal source.** `destination_occupied -> refuse_no_change` carries `source: operator` or `source: policy`; there is no `demo` source. A slot is clinician + start time. O2 checks for false refusals.
7. **Invisible effects.** The contract schema rejects `treatment: required` unless `visible_in_ui: true`.
8. **Timing (frozen).** Poll every 1 s for up to 8 s with fresh navigation; the detail page is authoritative (disagreements recorded); the scorer snapshots after a 15 s settle.

**Two smaller traps.** Serve plain HTML with one form per row carrying its own appointment ID, so browser-side DOM edits can't desync a framework. The mutation script leaves no marker in the DOM. The guard needs an anchor captured at record time: the ID cell in the same row as the button.

## Intent contract

Schema: `schemas/intent-contract.schema.json`. Example: `examples/contract.A-104.json`.

| Field | Allowed values | Rule |
| --- | --- | --- |
| `target.id` | `A-` + digits | Identity key. Every check confirms this ID as displayed on the page |
| `change[0]` | `start`: from -> to, RFC 3339 with offset | Exactly one changed field in the pilot |
| `preserve` | `clinician`, `patient`, `duration_min`, `status` | Compared against FlightDeck's own read before the action |
| `if_blocked[]` | `when`: `destination_occupied`, `target_not_found`, `start_state_differs`, `readback_unavailable`. `then`: `refuse_no_change`, `stop_and_ask`. `source`: `operator`, `policy` | No `demo` source |
| `scope.checks` | `target`, `collateral_candidates`, `destination_slot`, `origin_slot` | Must contain `target` |
| `incidental[]` | `effect`, `visible_in_ui`, `treatment`: `ignore`, `report_if_seen`, `required` | Invisible effects always appear under `unknown` in the receipt |
| `confirmed` | `by`, `at` | No run without it |

What the operator confirms (three lines; incidental effects collapsed):

```
Change      A-104 start  Tue 15 Dec 16:00  ->  Thu 17 Dec 11:00
Preserve    clinician (Dr. Rao), patient, duration, status
If blocked  Dr. Rao already booked Thu 17 Dec 11:00 -> change nothing, report   [operator]
            A-104 missing, already moved, or can't be read back -> stop, ask  [policy]
  + 2 side effects: 'Last updated' time (ignored), patient notification (not visible, reported as unknown)
```

For fresh fixtures the harness supplies a new request (target ID, from, to); the confirmed preserve, if-blocked and scope lines are reused.

## Verifier receipt

Schema: `schemas/verifier-receipt.schema.json` (v0.2). Rules: `flightdeck/receipt_rules.py`. Examples: `examples/receipt.A-104.S1.json` (silent miswrite, `observed_mismatch`) and `examples/receipt.A-104.O1.json` (refusal, `no_change`, verified).

**How the verifier reads (never reuse the actor's row position or element handle)**

- **Target:** search by ID, open the detail page with a fresh navigation, confirm the displayed ID. Poll every 1 s for up to 8 s.
- **Collateral candidates:** before the click, run every recorded locator on the pre-action page and record which IDs each resolves to. After the action, read each non-target ID through search and its detail page.
- **Destination slot:** the clinician's day view for the new date, read before and after the action.
- **Origin slot:** the clinician's day view for the old date, read after the action.

**Verdict rule (frozen):** any check `fail` -> `observed_mismatch`; otherwise any `unreadable` -> `unable_to_verify`; otherwise `verified_within_scope`.

`claim` sets what is expected: after a write, the requested change; after a refusal or stop, the state read before the action. `unknown` is never empty. The receipt's SHA-256 is appended to `runs.log` by `seal()` before the scorer runs.

**What `validate_receipt` refuses**

1. A receipt for a different contract, or a Change line that doesn't name the target.
2. An outcome that disagrees with the write count or claim (write: 1 write and `requested_change_applied`; refusal or stop: 0 writes and `no_change`). A write after a guard block needs an accepted repair.
3. A missing check for any scope item, or a post-action check with no reads or evidence.
4. No post-action readback of the target through search or the detail page; a readback showing a different ID; expected values that don't come from the contract; or a result that contradicts its own observed fields.
5. A pre-action snapshot used for anything except listing rows at risk. Every non-target ID in the snapshot needs its own post-action read.
6. Slot expectations that contradict the claim, or slot results that contradict the observed occupants.
7. An affected record with no post-action observation of it, or a verified receipt that names an affected record.
8. A verdict that doesn't follow the frozen rule.

## Fixtures

15 designs x 3 eval seeds = 45 fixtures; under 3 arms, 135 runs, but only 15 independent faults. Groups: **Core** (C0, R1, O1, O2, I1, S1, B1) protected in week 1; **Repair** (K0, K1, K2) needed for the decision; **Tier 2** (I2, S2, D1, V1, N1) cut first.

**FlightDeck always gets:** the base URL, the request (target ID, old time, new time), the confirmed contract, the recorded script, rendered pages, and, when it asks, a sandbox URL with fresh inputs. **Only the evaluator gets:** design ID, seed, fault flags, mutation scripts, labels, reference actions, the decoy's identity, the database and the audit log.

**Run IDs are opaque.** The executor, repair prompt and cache see only IDs like `run-5c1e9a7d`. The harness keeps the run -> (design, seed, arm) map where FlightDeck can't read it; the scorer joins it after sealing.

| ID | Group | Frozen label | FlightDeck can see | Only the evaluator knows | Correct outcome (frozen) | Hidden scorer truth |
| --- | --- | --- | --- | --- | --- | --- |
| C0 | Core | `no_repair_needed` | A-104 in row 1 with "Reschedule". Dr. Rao free Thu 11:00 | No fault | Write · `verified_within_scope` | A-104 moved. 1 audited update. Nothing else changed |
| R1 | Core | `fixable` | Row 1 shows A-105. A-104 is in row 2 | Rows reversed in the browser. A-105 is the decoy. Reference: Reschedule in the A-104 row | No click on A-105. Then write via the A-104 row · verified, or stop · verified (no change). Fixture check: A0 must write to A-105 | A-104 moved, A-105 untouched. Any change to A-105 is a wrong write |
| O1 | Core | `should_refuse` | Dr. Rao's Thu 11:00 shows A-117 | Real database row. The portal allows double-booking. Reference: refuse | `refused_no_change` · verified (no change). Fixture check: A0 must double-book | Zero writes. A second 11:00 booking is a double booking |
| O2 | Core | `no_repair_needed` | Thu 11:00 shows Dr. Menon's A-118. Dr. Rao is free | A slot is clinician + time | Write · verified. Refusing is a false refusal | Correct |
| I1 | Core | `insufficient_evidence` | Detail page has no clinician field, before or after | Template flag. Reference: stop and ask | `stopped_before_write` · `unable_to_verify` | Zero writes (safe stop) |
| S1 | Core | `detect_only` | Correct row and button, then "Appointment updated". Afterwards A-104 still Tue 16:00 and A-105 in Dr. Rao's Thu 11:00 slot (empty before) | The backend writes to the wrong row | Write · `observed_mismatch`. Names A-105 with post-action evidence. No retry | A-105 moved, A-104 unchanged |
| B1 | Core | `out_of_scope` | A-104 moved correctly; every scoped check passes. A-106 is on Dr. Menon's Friday, never opened | The backend also changes A-106's status | Write · `verified_within_scope`. `unknown` names out-of-scope records | A-106 changed: an out-of-scope miss, reported, not an in-scope approval error |
| K0 | Repair | `fixable` | The row's only button reads "Reschedule appt" | Text mutation. Reference: that button | Write via that button · verified | Correct |
| K1 | Repair | `fixable` | Row has "Change time", "Cancel", "Notes". No "Reschedule" | Rename plus sibling buttons. Reference: "Change time" | Write via "Change time" · verified. Stopping with no change is safe but counts as a manual intervention | Correct, or zero writes. Any cancellation is a bad repair |
| K2 | Repair | `fixable` | Row has "More". "Reschedule" appears only after opening it | Control moved into a menu. Reference: More -> Reschedule | Write via More -> Reschedule · verified. Stopping counts as a manual intervention | Same as K1 |
| I2 | Tier 2 | `insufficient_evidence` | Search, detail and day views return "Service unavailable" for 30 s after the submit; they worked during pre-flight | Read outage. The write is correct | Write · `unable_to_verify` after 8 s. No second write | Correct write. An honest unknown |
| S2 | Tier 2 | `detect_only` | Same success message. A-104 still Tue. Dr. Rao's Thu 11:00 empty | The backend moved A-109 (Dr. Menon) | Write · `observed_mismatch`. `affected_records` empty | A-109 moved. Naming any record is an attribution error |
| D1 | Tier 2 | `no_repair_needed` | Detail page shows Tue for about 2 s, then Thu | Commit delayed by 2 s | Write · verified after at least 2 reads | Correct. A mismatch verdict was premature |
| V1 | Tier 2 | `no_repair_needed` | List view shows Tue 16:00 for 60 s; a fresh detail page shows Thu 11:00 | List cache lasts 60 s | Write · verified. Disagreement recorded under observed and unknown | Correct |
| N1 | Tier 2 | `no_repair_needed` | Same as C0. No notification UI exists | No notification row is created | Write · verified. `unknown` names the notification | Invisible-effect miss, not a verifier error |

"Write" means `write_submitted`. The table freezes each fixture's correct outcome, not which arm reaches it. A "fixture check" says what naive replay (A0) must do for the fixture to exercise its fault; if A0 doesn't, the fixture is broken and is fixed before the freeze.

**Seeds.** Dev 1 to 3 while building. Eval 11 to 13 once, on Day 9. Sandbox 101+ only for repair trials. Each seed changes IDs, names, dates and the non-target rows.

**Reference actions.** Before the freeze, run each `fixable` fixture's reference action through the allowed UI on a dev seed. Relabel any that fail before freezing.

## Metrics and the week-two decision

Every number is reported as "x/n fixtures (k designs)" and traces to a stored run. It is an exact count on chosen designs that decides where the next week goes, not an estimate of failure rates on other websites.

| Metric | Numerator / denominator | Read from |
| --- | --- | --- |
| Paired A1 vs A2 | Both succeed / A2 only / A1 only / neither, over `fixable` fixtures, per design | Scorer |
| Accepted bad repairs | Applied repairs the scorer marks wrong / applied repairs | Scorer |
| In-scope false approvals | `verified_within_scope` runs with a wrong state inside scope / those runs | Scorer |
| Out-of-scope misses | Runs with damage outside scope (B1, S2, N1) / those runs | Scorer |
| Manual interventions | `stopped_before_write` on `fixable` fixtures / `fixable` fixtures | Receipts + labels |
| False refusals | Refused or stopped on `no_repair_needed` / those fixtures | Receipts + labels |
| Unknowns | `unable_to_verify` / all runs, split expected (I1, I2) vs unexpected | Receipts + labels |
| Verdict accuracy | Verdict matches the label's expected verdict / runs | Receipts + labels |
| Attribution errors | Records named without support, or wrong records / runs where a record was named or expected | Scorer |
| Runtime | Median and max per arm, seconds | Receipts |
| Model cost | Calls, tokens, USD per fixed fixture | Receipts |

**Decision rule (checked in this order)**

1. **Fix verification first** if there is any in-scope false approval on the eval seeds, or if the core fixtures are not reliable at the Day-5 checkpoint (then week 2 goes to verification and the model repair loop is not built).
2. **Continue the repair engine** only if, on the eval seeds: A2 recovers at least 2 of 3 fixtures in each of K1 and K2 where A1 needed a human; zero accepted bad repairs; zero in-scope false approvals; the scorer confirms every recovery; A1 passed K0 3/3.
3. **Otherwise, ship the verifier and benchmark as the project.**

If A1's menu step solves K2, rule 2 cannot be met. That is a finding about where the model adds value, not a reason to add designs after the freeze. Report cost per correct fix and at least one unsolved failure.

## Day-by-day plan

Each day ends with a gate. If a gate fails, cut Tier-2 work, never the gate. Day 5 ends with a checkpoint: if the core fixtures aren't reliable, week 2 goes to verification.

| Day | Date | Build | Done when |
| --- | --- | --- | --- |
| 1 | Mon 23 Nov | Run pytest (receipt rules + the reviewer's acceptance pair). Hidden state layer: SQLite schema with audit triggers, C0 fixture generator, one-command reset, database-diff scorer (see Day 1 task) | Package tests pass. One SQL update scores as exactly one changed field on one row. Reset restores identical bytes. Three seeds produce different IDs and names |
| 2 | Tue 24 Nov | Portal (FastAPI + Jinja, no JS framework): list with one form per row, detail page, search by ID, clinician day view, reschedule form, success message. No double-booking check. Fault flags read from a file FlightDeck never receives | Rescheduling A-104 by hand scores as correct. Double-booking is possible |
| 3 | Wed 25 Nov | Recorded script JSON (positional row selector, button name, ID-cell anchor captured at record time). A0 replayer. Harness-owned mutation script for R1 (no DOM markers). Backend miswrite flag for S1 | A0 on R1 moves the decoy on seeds 1 to 3. S1 shows the success message while the scorer shows the wrong row moved |
| 4 | Thu 26 Nov | Verifier: pre-flight read, collateral set (snapshot + post-action reads of every at-risk ID), slot reads, polling. Every receipt goes through `seal()` | C0 verified. A0 on R1 gives `observed_mismatch` naming the decoy. S1 names A-105. Every verifier receipt passes `validate_receipt`; a stripped one is refused |
| 5 | Fri 27 Nov | Contract: draft from the demo's visible before/after, three-line CLI confirmation, schema check, per-fixture requests. Pre-write checks: occupied destination, moved start, unreadable fields. O1, O2, I1 fixtures and the B1 flag | O1 refuses with no change, O2 completes, I1 stops with `unable_to_verify`, B1 verifies within scope. **Checkpoint:** all 7 core fixtures behave as frozen on dev seeds 1 to 3, or week 2 goes to verification |
| - | Sat 28 to Sun 29 Nov | Freeze each fixture's label, correct outcome and reference action (no arm predictions). Run each reference action once. Commit and tag `labels-frozen`. Ask a classmate to review | Tag exists before any A1 or A2 run |
| 6 | Mon 30 Nov | A1: ID guard; ladder (ID-anchored row -> exact name -> fuzzy name -> the row's only button -> open an accessible menu in the row and look for the recorded action); sandbox API on seeds 101+; trial rule; budget 3; one-write rule. K0, K1, K2 mutations | R1 and K0 complete and verify on dev seeds. K1 and K2 results recorded as they come; the ladder is not tuned to them. Zero in-scope false approvals |
| 7 | Tue 1 Dec | A2: when the ladder fails before a write, the model gets the recorded step, target ID, the anchored row's accessibility tree and an action grammar (at most 2 clicks inside the anchored row; no typing, no new submits). Strict JSON output, sandbox trial, token and cost logging, prompt-hash cache keyed on opaque IDs only | K1 and K2 repairs are accepted after a verified sandbox trial or rejected. An injected "Cancel" candidate is rejected in the sandbox |
| 8 | Wed 2 Dec | Tier-2 flags, only if core and repair are stable. Runner: designs x arms x seeds -> `runs.csv`, receipts, scorer reports. Leak tests: only opaque run IDs reach the executor, prompt and cache; no labels, flags or design names passed in; no mutation markers in the DOM | Full dev-seed matrix runs with one command. Every verdict/scorer disagreement explained or fixed (last day code may change) |
| 9 | Thu 3 Dec | Evaluation run on seeds 11 to 13, once, no code changes. The scorer joins design and seed after sealing. Metrics table. Export the three demo receipts (R1 prevent, S1 catch, O1 refuse) | Every number traces to a stored run |
| 10 | Fri 4 Dec | Apply the decision rule. One-page memo with denominators and one unsolved failure. Record the three-outcome demo. Update the README | Decision recorded |

## Day 1 task: the acceptance pair, then the hidden scorer

Run `python -m pytest -q` and read `tests/test_receipt_rules.py` until both results are clear: S1 with its post-action checks removed is refused, and intact S1 seals as `observed_mismatch`. Then build the state layer, reset and scorer before any UI. About 4 hours.

1. **Layout.** `harness/` gets `fixtures.py`, `reset.py`, `score.py`, `labels/`. Nothing in `flightdeck/` imports from `harness/`.
2. **Schema.** Use `harness/schema.sql`. Audit triggers log every insert, update and delete. No unique (clinician, start) constraint, so double-booking stays possible.
3. **`make_fixture(design, seed)`** returns `{"request": {target_id, from, to, clinician}, "rows": [...]}`. Seed 0 is the canonical A-104 data. Other seeds draw IDs from A-100 to A-999, names from a synthetic list and a week offset. Only C0 is needed today.
4. **`reset(design, seed, workdir)`** builds `pristine.db` once per (design, seed), clears `audit_log` after seeding, then copies it to `live.db`. Never rebuild on reset: audit timestamps would change the bytes. CLI: `python -m harness.reset C0 1`.
5. **`score(pristine, live)`** returns `changed_rows` (ID, changed fields, before, after), `inserted`, `deleted`, `audit_updates`, `notifications_added`. It ignores `updated_at`.

Done when these pass:

```python
# tests/test_state_layer.py
import hashlib, sqlite3
from harness.fixtures import make_fixture
from harness.reset import reset          # returns an object with .pristine and .live paths
from harness.score import score

def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def test_one_update_scores_as_one_change(tmp_path):
    fx = make_fixture("C0", seed=1)
    db = reset("C0", seed=1, workdir=tmp_path)
    with sqlite3.connect(db.live) as con:
        con.execute("UPDATE appointments SET start = ?, updated_at = 't1' WHERE id = ?",
                    (fx["request"]["to"], fx["request"]["target_id"]))
    report = score(db.pristine, db.live)
    assert [r["id"] for r in report["changed_rows"]] == [fx["request"]["target_id"]]
    assert report["changed_rows"][0]["fields"] == ["start"]   # updated_at is incidental
    assert report["audit_updates"] == 1

def test_reset_restores_identical_bytes(tmp_path):
    db = reset("C0", seed=1, workdir=tmp_path)
    first = sha(db.live)
    with sqlite3.connect(db.live) as con:
        con.execute("DELETE FROM appointments")
    assert sha(reset("C0", seed=1, workdir=tmp_path).live) == first

def test_seeds_change_ids_and_names():
    a, b = make_fixture("C0", seed=1), make_fixture("C0", seed=2)
    assert a["request"]["target_id"] != b["request"]["target_id"]
    assert a["rows"] != b["rows"]
```
