# Phase 11 Stage A review corrections

Status: initial review; implement before Stage B. Use the same Phase 11
OpenCode conversation. Do not commit, push, install a scheduler, read `.env`,
run live ingestion or access Supabase. Preserve Stage A scope until Codex accepts
the gate. Follow `phase_11_plan.md` section 8.

## A. Enforce the strict profile contract and its effective limits

Codex reproduced all these accepted inputs through
`AutomationConfig.model_validate_json(json.dumps(profile))`:

- `version = true` and `version = 1.0`;
- `backup.automatic_deletion = 0`;
- a duplicate source/target job with a different job ID;
- cycle `job_timeout_seconds = 10` with job `timeout_seconds = 900`;
- 168 required accepted intervals in the fixed 24-hour coverage window.

Pydantic strict mode does not make `Literal` values type-sensitive. Add
explicit before validators for exact literal scalar types. Reject duplicated
source-target work across renamed jobs (or one job per source in this profile).
Reject impossible/inconsistent settings or apply one documented effective
timeout cap everywhere: config validation, planner, summary and supervisor.
The current runner ignores the cycle's advertised per-job limit.

Bound the operations profile at the existing 400 MiB ingestion stop; do not
advertise a healthy 1 GiB/100 GiB setting while the worker stops at 400 MiB.
Reject accepted-interval thresholds above the actual coverage-window size,
including target overrides. Reject contradictory duplicate backup-age fields
or remove the redundant one before Stage B depends on it. Keep the example
profile valid and record tests using exact rejection/effective-value assertions.

Also wrap profile file decoding/open errors in a stable AutomationError. The
current `read_text` runs outside its `try`; invalid UTF-8 or read failures escape
the intended constant diagnostic boundary. Add bounded config-file size and
regular-file checks if needed for safe parsing; avoid unrelated registry changes.

## B. Validate event values and recheck stderr codes before persistence

`sanitize_event` currently allowlists keys but retains arbitrary string values
under `status`, `error_code` and `target`. Codex reproduced an unknown string
and unreviewed target passing through unchanged. `extract_stderr_codes` accepts
any lowercase token after `Ingestion stopped:`. `_job_record` then copies those
tokens without redaction or a known-code check; a synthetic canary equal to a
known redaction secret survived into its primary error code.

Use event-specific schemas for known statuses, finite nonnegative integer
counts (reject bools), reviewed source/target/product identities, UUIDs and
offset-aware timestamps. Keep an explicit constant code registry for emitted
ingestion/database/supervision codes; map unknown/malformed codes to a constant
such as `unrecognized_child_error`, never the original text. Apply this both
when collecting stdout/stderr and at final persistence. Do not use arbitrary
scrubbed strings as a substitute for the value contract. Redaction remains a
second defense.

Add regression tests for unknown and secret-canary stderr codes, malformed
types, non-finite numbers, unreviewed targets and arbitrarily long strings. Tests
must prove the exact canary is absent from the summary and alert JSON. Legitimate
actual Phase 3 events must retain their intended status/count/window meaning.

## C. Finish scoped verification after code changes

Run focused automation tests and the research/whitespace regression first.
Record failures as well as the final result; do not claim test execution from
a pipeline's final `tail` status. Run the full offline/isolated suites once at
the coherent delivery boundary; only repeat tests for materially changed code.
Do not weaken an assertion just to match an implementation that violates the
plan. Keep Phase 5–10 evidence unchanged and do not mark Phase 11 complete yet.

An internal reviewer is examining supervision, lock, deadlines and file lifecycle
separately. Codex will append those accepted findings here before the correction
dispatch; wait for the complete review message rather than starting Stage B.

## D. Gate 1 supervision and lock corrections

The Gate 1 review found four material issues in the core runner:

1. Retain the process-group ID immediately after spawn. If the leader exits on
   `SIGTERM` while a descendant remains, deriving the group from the dead PID
   can fail and leave the descendant alive while the checkout lock is released.
   Terminate/kill the retained process group and reap it before returning.
   Add a real parent-plus-grandchild test where the parent exits on TERM but the
   grandchild keeps running; assert the descendant is gone and the lock can be
   reacquired only after cleanup.
2. Handle external `SIGINT`/`SIGTERM` inside the supervised cycle. Route the
   signal through child-group cleanup, write a stable failed/interrupted
   summary and alert without `SUCCESS.json`, and release the lock after cleanup.
   Add real signal tests. `KeyboardInterrupt` must not leave an empty reserved
   directory.
3. Include database preflight in the cycle monotonic deadline. Pass remaining
   budget into preflight, bound connection/statements against it, and test that
   an expired/blocked preflight starts no child and writes defined failure
   evidence. Account for terminate grace and stream drain when claiming the
   cycle deadline includes finalization.
4. Prove cross-process lock exclusion and owner-death release with a helper
   subprocess: holder acquires, second process reports contention, holder exits,
   then acquisition succeeds. Keep the existing same-process test as a unit
   check.

Do not weaken these tests or proceed to Stage B until all four are covered and
the Stage A focused suite passes. Keep correction A/B tests and the full suite
evidence.
