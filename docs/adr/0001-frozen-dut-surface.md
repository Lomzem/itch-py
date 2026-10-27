# The DUT's surface is frozen

`Rig.connect("bench3", AcmeWidget)` returns a DUT: an instance of the Profile that drives both its Fields and its Rig's Channels. Its Fields are attributes named by the Profile author, so every method the DUT has is a name no Field can take. If the DUT grew whenever the Rig did, a Profile that loads today could stop loading after an itch-py upgrade.

So the DUT exposes exactly the eight Channel verbs (`set`, `clear`, `write`, `apply`, `set_all`, `clear_all`, `get`, `get_all`), `disconnect`, `rig`, context-manager support, and its Fields. Rig administration, such as `label`, `holder`, `lock`, `status`, `set_label` and the Wi-Fi and address settings, lives on `dut.rig` only, with no forwarding. New Rig features go on `Rig`, never on the DUT. A Field named after one of those ten names, or starting with `_`, raises `ProfileError` when its Profile class is defined, so the author renames it before any script runs. The reserved list stays fixed under this design. Accepted cost: QA write `dut.rig.status()` rather than `dut.status()`.

This records the current design. During alpha it may be deliberately revised under the [development-stage policy](../../AGENTS.md#development-stage); update this decision and the Profile guide when doing so.

The method names `set`, `clear` and `set_all` are a deliberate exception to the shared glossary, which avoids "set/unset" for On / Off and defines Clear as turning every Channel off. They are short verbs QA type all day, so prose keeps the glossary's words: docs say "turn on" and "turn off", and `clear_all()` is the Clear. The glossary in itch stays as it is.
