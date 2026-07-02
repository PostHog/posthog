"""Pure helpers for decomposing snapshot identifiers.

A Storybook identifier is assembled in
``common/storybook/.storybook/test-runner.ts`` as::

    {story-id}[--{widthName}]--{theme}[--{browser}]

- ``theme`` is always present (``light`` / ``dark``)
- ``widthName`` is optional (multi-viewport stories)
- ``browser`` is appended only when the browser is not chromium

``story_stem`` strips those trailing facet tokens so a per-story threshold
override keys on the story itself and covers every theme/viewport/browser
variant at once. It is deterministic — the stem computed when an override is
created matches the stem computed at classification time — so it stays
self-consistent even for identifiers that don't follow the Storybook grammar.
"""

_THEMES = frozenset({"light", "dark"})
_WIDTH_NAMES = frozenset({"narrow", "medium", "wide", "superwide"})
_BROWSERS = frozenset({"chromium", "webkit", "firefox"})


def story_stem(identifier: str) -> str:
    """Strip trailing browser, theme, and viewport-width tokens from an identifier."""
    tokens = identifier.split("--")
    if len(tokens) > 1 and tokens[-1] in _BROWSERS:
        tokens = tokens[:-1]
    if len(tokens) > 1 and tokens[-1] in _THEMES:
        tokens = tokens[:-1]
    if len(tokens) > 1 and tokens[-1] in _WIDTH_NAMES:
        tokens = tokens[:-1]
    return "--".join(tokens)
