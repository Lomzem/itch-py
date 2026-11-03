---
name: verify-itch-py
description: Verify itch-py's Python library and CLI user journeys against an isolated release simulator when changing Channels, Profiles, Locks or labels.
---

# Verify itch-py

The primary surface is the Python library used by QA scripts; the secondary
surface is the `itch` CLI. Start with [the feature map](features/README.md).
Use this recipe from the repository root with Python 3.11+ and `uv` installed.

## Launch

```sh
uv sync --locked
uv run python .agents/skills/verify-itch-py/drive.py doctor
```

The helper reuses `tests/itch_release.py` to download and hash-check the pinned
release's simulator and vectors, then `tests/conftest.py`'s `RunningSim` to
launch it. The cache can be reused offline after the first download. No Cargo,
sibling checkout, physical Rig, credentials or seeded data is needed. This
intentionally verifies the published release rather than newer sibling source.
The release helper currently supports Linux x86-64 and Windows x86-64; other
platforms need a matching simulator and are outside this recipe.

Each invocation owns a fresh simulator with empty, in-memory state on an
OS-assigned loopback TCP port. Two invocations can run side by side after the
release cache is populated; serialize first-time downloads into the shared cache.
`READY tcp://127.0.0.1:…` followed by successful public `status()` and
`get_all()` reads establishes a usable instance. The process stops before the
command returns. There is no server for the next command to reuse.

## Doctor

Run the `doctor` command above first whenever anything looks off. Its read-only
public API checks require Hardware ID `02:00:00:51:4D:01`, the firmware version
from the release pin, no Holder, and all Channels off. Every drive also runs
these checks against its own instance before mutating it. Doctor also requires
the imported package to come from this checkout's `src/itch` and records its Git
revision alongside the installed package version and simulator release. A failed command
means the journey is unverified; inspect its transcript before proceeding.

## Drive

```sh
uv run python .agents/skills/verify-itch-py/drive.py channels
uv run python .agents/skills/verify-itch-py/drive.py profiles
uv run python .agents/skills/verify-itch-py/drive.py locks
uv run python .agents/skills/verify-itch-py/drive.py labels
```

Choose the mapped features affected by the change. Each command executes the
public API actions in its feature recipe; `labels` additionally invokes both
the actual `python -m itch label` CLI and the installed `itch label` console
command in subprocesses, with separate reconnect readback after each.

## Evidence

The command prints the absolute transcript path under
`.scratch/repo-improvements/verification-evidence/<feature>-<unique-id>/transcript.txt`.
Keep that path in the task record. Evidence contains actions, observed values,
CLI stdout/stderr/exit status where used, reconnect reads, completion or the
exception, and cleanup success. Require exit code zero and `PASS <feature>`.
CI retains these transcripts in the `verification-evidence` artifact, including
failed journeys; download that artifact when a CI journey fails.

Exercise the real user path, capture the action and resulting state, and verify
effects with fresh public reads, including a separate connection where the
feature requires it. Use no internal setters, fake responses or test-only
protocol endpoints. These are repeatable journey checks, while the regression
suite remains the owner of detailed contract proof. A transcript alone cannot
prove physical contacts, USB discovery, mDNS, Wi-Fi association, persistence
across power cycles, or DUT behavior. Report these as unverified when relevant.
This is a simulator run, not a dry-run: commands really change its state.
Downloads can access GitHub; all Rig traffic uses the owned loopback simulator.
Only the made-up Profile in `docs/profile_template.py` is used.

## Cleanup

`RunningSim` stops and waits for the exact child it started on successful and
failed drives. The simulator has no persisted data directory to delete. Never
kill by process name. Allow the helper to unwind on interruption so its context
manager can run; a force-killed helper may require identifying and stopping its
specific orphan child. Evidence directories survive cleanup, including failures.
Release downloads and the development environment are reusable dependencies,
not scratch instances. Check the printed transcript still exists after exit.

## Helpers

`drive.py` is executable and also supports the portable Python invocations above.
It accepts exactly one of `doctor`, `channels`, `profiles`, `locks`, or `labels`;
run `uv run python .agents/skills/verify-itch-py/drive.py --help` for usage.
Extend the feature map alongside behavior changes. Use
`$maintain-verification-skill` in Codex or `/maintain-verification-skill` in Claude
Code when maintaining this skill and its map.
