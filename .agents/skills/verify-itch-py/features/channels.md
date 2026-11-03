# Channel changes and readback

QA scripts turn individual Channels on or off, apply a mask, and read back the
current state without disturbing unrelated Channels.

## Sub-features

- `channels-selective`: `set`, `clear` and `write` affect only named Channels.
- `channels-mask`: `apply` preserves Channels outside its mask.
- `channels-readback`: individual and complete reads reflect the Rig; disconnect preserves state.

## How to get to it (user POV)

Import `Rig` and `ch`, then use `with Rig.connect("tcp://127.0.0.1:PORT") as rig:`.
The helper supplies its owned simulator URL. Physical/automatic connection paths
are outside this mapped journey.

## Driving it with drive.py

Preconditions: a fresh simulator passes doctor, with all Channels off.

- **Run:** `uv run python .agents/skills/verify-itch-py/drive.py channels`.
- **Selective writes:** `rig.set(1, 5)` reads as `0x0011`; `rig.clear(1)` reads
  as `0x0010`; `rig.write(set=[2], clear=[5])` reads as `0x0002`.
- **Mask write:** `rig.apply(ch(9), mask=ch(9, 10))` makes `rig.get(9)` true
  and the full state `0x0102`, preserving Channel 2.
- **Reconnect:** after leaving the context, a new `Rig.connect(url, lock=False)`
  reads `0x0102` and `status().holder is None`.
- **Proof:** transcript shows the actions, full state, reconnect state and `PASS channels`.

## Gotchas

- Channel 1 is the rightmost bit, not Channel 16.
- No simulated read proves physical contact continuity or actual DUT behavior.
- `set_all`, `clear_all`, state restore and argument validation remain additional
  paths to map when changes affect them.
