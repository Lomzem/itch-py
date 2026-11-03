# Locks

The default connection Locks the Rig, another Holder may still read it, and
disconnecting releases the Lock without clearing Channels.

## Sub-features

- `locks-default`: connecting acquires the named Holder's Lock.
- `locks-refusal`: another Holder cannot acquire that Lock.
- `locks-observe`: a connection with `lock=False` can observe the held Rig.
- `locks-release`: the next Holder can connect after context exit.

## How to get to it (user POV)

Pass `holder="verification-alice"` or `holder="verification-bob"` to
`Rig.connect(url)`. Add `lock=False` for a read-only observer. The helper uses
distinct Holder names solely against its owned simulator.

## Driving it with drive.py

Preconditions: a fresh simulator passes doctor and has no Holder.

- **Run:** `uv run python .agents/skills/verify-itch-py/drive.py locks`.
- **Acquire:** Alice connects and turns Channel 1 on.
- **Refuse:** Bob's ordinary `Rig.connect()` in a separate process raises `LockedError`.
- **Observe:** Bob connects with `lock=False`, reads state `0x0001` and Holder
  `"verification-alice"`.
- **Release:** Alice's context ends; Bob then connects normally, sees Holder
  `"verification-bob"`, and reads the unchanged state `0x0001`.
- **Proof:** transcript captures refusal, observer reads, new Holder/state and `PASS locks`.

## Gotchas

- Two scripts with the same Holder share a Lock; use distinct names to verify refusal.
- Keep Bob in a separate process: connecting again to an endpoint within one
  process intentionally disconnects that process's existing Rig connection.
- Takeover, explicit `rig.lock()` scopes and crash recovery are separate paths
  currently owned by the regression suite, not verified by this journey.
