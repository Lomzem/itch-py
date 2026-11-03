# Profile settings

A Profile lets QA write meaningful DUT settings, read Values and batch several
Fields into one update. Conflicting Fields must leave Channel state unchanged.

## Sub-features

- `profiles-field`: set and read a named Value.
- `profiles-batch`: apply several named Fields together.
- `profiles-conflict`: refuse conflicting Fields without changing Channels.

## How to get to it (user POV)

Copy `docs/profile_template.py` beside a QA script, then use
`Rig.connect(url, AcmeWidget)` and the DUT's named Field attributes. The helper
imports that actual template and supplies its owned simulator URL.

## Driving it with drive.py

Preconditions: a fresh simulator passes doctor; the Profile template imports.

- **Run:** `uv run python .agents/skills/verify-itch-py/drive.py profiles`.
- **Field:** `dut.resolution.set("1080p")` reads as `"1080p"` and Channel state `0x0002`.
- **Batch:** `dut.apply(resolution="720p", standby="enabled")` reads as state `0x0041`.
- **Conflict:** `dut.apply(picture="bars", tone="silent")` raises `BatchConflictError`
  and state remains `0x0041`.
- **Reconnect:** a new DUT reads resolution `"720p"` and standby `"enabled"`.
- **Proof:** transcript captures the Field action, batch Values/state, refusal,
  reconnect reads and `PASS profiles`.

## Gotchas

- This made-up DUT is the public template, not a real product Profile.
- A template change that removes these Values is a failed precondition; update
  the journey to the new intended feature, never silently skip the assertions.
- Aliases, non-default Encodings and overlapping compatible batches need further
  mapped journeys when affected by a change.
