# PROTOTYPE: Profile syntax (throwaway)

Answers one question for ticket 18 ("Python API and Profile authoring"): **can QA engineers who aren't Python-adept write and use Profiles on their own, with autocomplete?** Nothing here is the real `itch-py`. `itch_prototype.py` is a fake library, and the Rig is an in-memory fake that prints its Channels. "Acme Widget" is a made-up DUT.

Needs Python ≥ 3.11 and nothing else. Open this folder in VS Code (Pylance) or Neovim (pyright/basedpyright); `pyrightconfig.json` turns on type checking so typos get red squiggles. The ty extension is not supported yet: it can't tell a Field's Values from the Profile, so they don't autocomplete.

## Files

- `acme_widget.py`: the Profile.
- `script.py`: a QA script using it. Run with `python script.py`.
- `show_errors.py`: the message for each common mistake.

## Things to try

1. In `script.py`, delete `night` from `dut.mode.set("night")`, type `"`, and see whether VS Code lists the Values, including the alias `movie`. (Press Ctrl+Space if not.)
2. Change a Value to `"nigth"` and look for the red squiggle.
3. Type `dut.` and see the Fields offered.
4. Run a script and read the `testing ...` lines: `dut.mode.encodings("night")` goes through all 4 Encodings of `night`, and `dut.mode.all_encodings()` goes through every Encoding of every Value.
5. In a Profile, add a third Encoding to `eco`, or give an Encoding the wrong number of positions (VS Code can't catch the count; the message appears when the script runs).
6. `python show_errors.py` prints the message for each common mistake.
7. Read the Channels directly: `rig.get_channel(3)`, `rig.get_channels([1, 2])`, `rig.get_channels()`. Try `rig.set_channel(17, "on")` (the message appears when the script runs).
8. Write a Profile for a DUT you know and note what felt awkward.

## Ideas being tried

- **Encodings.** Some DUTs accept one setting through several switch patterns. Each pattern is an Encoding. List them one per line; `set("night")` writes the first, `set("night", encoding=3)` a specific one, and `encodings("night")` lets a test go through all of them, so one broken Encoding can't hide behind a working one.
- **Aliases.** `"movie": alias("cinema")`: another name for the same switches. `get()` returns `"cinema"`.
- **Fields sharing Channels.** `picture` and `tone` are the same switch; `refresh` is also part of `mode`. In a `batch()`, Values that disagree on a shared Channel are refused before anything is written.
