## Agent skills

### Issue tracker

Issues and specs live as local Markdown files under `.scratch/<feature>/`. Before reading or writing tickets, read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage roles. Before triaging issues or changing their status, read `docs/agents/triage-labels.md`.

### Domain docs

Before exploring the codebase, read `docs/agents/domain.md` for the shared glossary and decisions.

## Repository split

This repo owns the Python client. Firmware, simulator and protocol live in [Lomzem/itch](https://github.com/Lomzem/itch), usually checked out alongside it.
Before changing the protocol, coordinating work across repos, or handling CI or releases, read `../itch/docs/agents/project.md`, or its [GitHub copy](https://github.com/Lomzem/itch/blob/main/docs/agents/project.md).

## Public repo

`github.com/Lomzem/itch-py` is public and QA installs it straight from GitHub. Profiles for real AJA products live outside this repo, along with AJA product names and switch meanings. Examples, docs and tests use a made-up DUT.
