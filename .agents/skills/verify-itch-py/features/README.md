# itch-py verification map

This is the maintained map for the simulator-backed Python and CLI user journeys.
Read [the skill](../SKILL.md) for launch, doctor, evidence and cleanup.

## Baseline preconditions

- `uv sync --locked` succeeds at the repository root.
- The pinned release can be downloaded, or its hash-verified cache is populated.
- Each helper invocation launches its own empty simulator on an ephemeral port.
- Doctor confirms the expected simulator identity, firmware and unlocked Clear state.

## Driving conventions

Use `uv run python .agents/skills/verify-itch-py/drive.py <feature>` from the root.
The helper prints each user action before asserting observable results. It
uses the public API over real TCP; it owns and stops its simulator. Never point
these mutating recipes at an engineer's Rig. Baseline state is independent for
each feature. Add alternate entry points when a feature gains them.

## Proof and skip reporting

Keep each printed transcript path and require `PASS` plus exit code zero. Capture
action, result, and reconnect readback; CLI proof also records stdout, stderr and
exit status. Report failures with their attempted action and unmet precondition.
Do not substitute one entry point's success for another's failure or skip.

This initial map covers four core workflows. USB/mDNS discovery (`itch list`,
`list_rigs()`, automatic or named `Rig.connect()`), Wi-Fi/address provisioning,
physical contacts and power-cycle persistence need
additional journeys; no success here claims to verify those surfaces.

## Features

- [Channel changes and readback](channels.md): selective writes, mask writes, reconnect state.
- [Profile settings](profiles.md): Fields, batch writes and atomic conflict refusal.
- [Locks](locks.md): default Lock, read-only observation, refusal and release.
- [Labels](labels.md): Python rename, CLI rename, reconnect and Lock release.
