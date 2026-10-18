*Version: v0.1 (2026-10-18)*

# Tracks executed outside `trackrun`, and tracks that span several repositories

## Situation observed

A project adopted TODO Flow mid-goal to keep a long goal's requirements from being forgotten across context resets. Its work already ran through an existing dispatcher (visible terminal lanes, one executor per domain, a single integrator, a serialized production turn) over **three repositories** edited in per-lane clones, then integrated and promoted by a cutover script.

`todo-flow init` / `trackrun` assume:

1. one `--repo` and one base branch;
2. workers launched by the driver, in worktrees of that repo;
3. `writable_patterns` (default `*.py`, `tests/*.py`) and one `verify` argv for the repo.

None of these fit, so the project registered tracks as the canonical requirement list but executed them with its own dispatcher. The only way it found to record progress was to re-register each document with a new `history` entry (`register --expected-revision N`). That works but (a) bumps the document revision for status-only changes, (b) does not move `control` out of `idle`, and (c) leaves `results/` and `attempt-records/` empty, so the dashboard cannot show which conditions are met.

## Proposal (smallest change)

1. **External attempt record.** `todo-flow --state S record ID --condition C --status met|unmet|blocked --evidence PATH_OR_TEXT [--executor NAME]` appends an event and a result file without launching a worker and without changing the document revision. The dashboard shows per-condition status from these records.
2. **Executor mode `external`.** A track whose `workerPlan` (or request) says `executor: external` is never claimed by the driver; `trackrun` refuses it with a clear message instead of launching into the wrong repo.
3. **Multi-repo scope in the document, not the config.** Optional `repos: [{path, base, writable}]` in the track metadata, used only for display and for the external record's evidence paths. The single-repo config stays as is for driver-run tracks.

Non-goals: running cross-repo workers from the driver; replacing the project's own verification or promotion steps.

## Acceptance

- A track with `executor: external` can be selected, recorded condition by condition, and shown as complete when all required conditions are `met`, with no worker launched and revision unchanged.
- Existing single-repo tracks and `trackrun` behave exactly as before (current tests unchanged).
