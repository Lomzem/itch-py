# Domain docs

## Before exploring

The shared domain docs live in itch. Read its [glossary](https://github.com/Lomzem/itch/blob/main/GLOSSARY.md)
and relevant [decisions](https://github.com/Lomzem/itch/tree/main/docs/adr/)
before exploring the codebase. Use `../itch/GLOSSARY.md` and
`../itch/docs/adr/` when a sibling checkout is available.

Also read Python-specific decisions in this repo's `docs/adr/` when present.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, reconsider whether you're inventing language the project doesn't use, or note a real gap for `domain-modeling`.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding it. Name the ADR and explain why the decision may need reopening.
