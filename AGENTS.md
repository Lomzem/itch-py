## Audience

itch-py serves internal QA engineers with a basic understanding of the DUT and Python. They are capable users who can learn unfamiliar concepts; advanced Python knowledge and detailed product knowledge are not prerequisites. They have access to AI assistance. Type safety helps both engineers and their AI tools understand and use the API.

Focus on controlling and reading DUT switch configurations within existing QA procedures. Surrounding scripts and tools handle DUT pass/fail decisions, test-run organisation and reports. Broader test management needs an actual internal workflow to justify it.

## Design priority

The QA engineer's user experience is the top priority. Optimise for one engineer running one script per Rig. Extra user steps or bookkeeping to handle rare multi-client or failure cases need a concrete justification; see the shared [single-engineer decision](https://github.com/Lomzem/itch/blob/main/docs/adr/0004-optimise-for-one-qa-engineer.md).

Accept additional library implementation complexity when it provides concrete, maintainable improvements to validation, error messages, editor completion or type checking.

Use convenient defaults when intent is unambiguous. Report ambiguity with a concrete way for the engineer to resolve it.

## Development stage

itch-py is in alpha, with no users yet. Breaking changes are acceptable during alpha. Keep documentation and examples consistent with the current API; revisit compatibility expectations when users begin relying on it.

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

`github.com/Lomzem/itch-py` is public to enable free CodeRabbit reviews. Expected use is internal only, with no external customers. QA installs it straight from GitHub. Profiles for real AJA products live outside this repo, along with AJA product names and switch meanings. Examples, docs and tests use a made-up DUT.
