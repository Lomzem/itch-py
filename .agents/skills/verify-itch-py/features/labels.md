# Labels

Rename a Rig from a script or the CLI and see the new Label on a fresh
connection. CLI completion releases its Lock.

## Sub-features

- `labels-python`: rename with `rig.set_label()`.
- `labels-cli`: rename with both module and installed-console CLI processes.
- `labels-readback`: reconnect sees the new Label with no Holder.

## How to get to it (user POV)

- Python: connect to the owned simulator and call `rig.set_label("verification-bench")`.
- Terminal: `uv run python -m itch label tcp://127.0.0.1:PORT verification-module`.
- Installed console command: `uv run itch label tcp://127.0.0.1:PORT verification-console`.

## Driving it with drive.py

Preconditions: a fresh simulator passes doctor with its default Label.

- **Run:** `uv run python .agents/skills/verify-itch-py/drive.py labels`.
- **Python rename:** set `"verification-bench"`, disconnect, and read that Label
  and no Holder from a fresh connection before either CLI command.
- **Module rename:** after disconnecting Python, invoke
  `python -m itch label URL verification-module`; require exit zero and the new
  Label in stdout; retain stderr too.
- **Console rename:** invoke `itch label URL verification-console` and require
  exit zero and the new Label in stdout.
- **Reconnect:** after each CLI command, `Rig.connect(url, lock=False)` reads the
  corresponding new Label and `status().holder is None`.
- **Proof:** transcript captures all three actions, CLI outputs, all reconnect
  states and `PASS labels`.

## Gotchas

- Persistence across connections is proven; persistence across a physical reboot is not.
- The Label is not used for discovery in this recipe; connections use the known TCP URL.
- Empty-label reset, storage faults and byte-length validation need additional
  proof when the relevant behavior changes.
