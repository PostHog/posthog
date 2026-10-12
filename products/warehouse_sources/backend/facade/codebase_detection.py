"""How the wizard tells that a codebase uses a source, declared by each source as `codebase_detection`.

The wizard projects these declarations into the detector registry it scans codebases with. See
`products/wizard/backend/tool_catalog/`.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import TypedDict, Unpack, cast

from posthog.dataclasses import frozen
from posthog.schema_enums import ProductKey


class Ecosystem(StrEnum):
    NPM = "npm"
    # Lowercase, with `_` replaced by `-`, the way the wizard normalizes Python dependency names.
    PYPI = "pypi"
    RUBYGEMS = "rubygems"
    COMPOSER = "composer"
    HEX = "hex"
    # Module path without a trailing `/vN` major-version element.
    GO = "go"
    CARGO = "cargo"
    # `group:artifact` coordinates.
    MAVEN = "maven"
    # Package URL without scheme or `.git`, lowercase, e.g. `github.com/getsentry/sentry-cocoa`.
    SWIFTPM = "swiftpm"
    COCOAPODS = "cocoapods"
    PUB = "pub"


class WizardSetupMode(StrEnum):
    # The agent collects credentials and creates the source from the terminal.
    IN_CLI = "in-cli"
    # The wizard opens the app's pre-filled new-source form in the browser.
    DEEP_LINK = "deep-link"


IN_CLI = WizardSetupMode.IN_CLI
DEEP_LINK = WizardSetupMode.DEEP_LINK


@frozen
class Detection:
    # None for a tool the wizard detects and reports but never offers as a source.
    setup_mode: WizardSetupMode | None
    packages: Mapping[Ecosystem, tuple[str, ...]]
    # Anchored regexes matched against `.env` key names. The wizard compiles them as JavaScript
    # regexes, so they must stay in the subset both engines read the same way.
    env_key_patterns: tuple[str, ...]
    # A host matches itself and its subdomains.
    script_hosts: tuple[str, ...]
    competes_with: tuple[ProductKey, ...]
    # Kinds that reach the same data through a more specific connector. When one of them also
    # matches, the wizard drops this one so the data is not imported twice.
    superseded_by: tuple[str, ...]


@frozen
class NotDetectable:
    reason: str


class _Signals(TypedDict, total=False):
    npm: tuple[str, ...]
    pypi: tuple[str, ...]
    rubygems: tuple[str, ...]
    composer: tuple[str, ...]
    hex: tuple[str, ...]
    go: tuple[str, ...]
    cargo: tuple[str, ...]
    maven: tuple[str, ...]
    swiftpm: tuple[str, ...]
    cocoapods: tuple[str, ...]
    pub: tuple[str, ...]
    env: tuple[str, ...]
    script_hosts: tuple[str, ...]
    competes_with: tuple[ProductKey, ...]
    superseded_by: tuple[str, ...]


def detect(setup_mode: WizardSetupMode | None, **signals: Unpack[_Signals]) -> Detection:
    # The package keyword names match the Ecosystem values, so a lookup by value finds them.
    by_name = cast(Mapping[str, tuple[str, ...]], signals)
    return Detection(
        setup_mode=setup_mode,
        packages={ecosystem: by_name[ecosystem.value] for ecosystem in Ecosystem if by_name.get(ecosystem.value)},
        env_key_patterns=signals.get("env", ()),
        script_hosts=signals.get("script_hosts", ()),
        competes_with=signals.get("competes_with", ()),
        superseded_by=signals.get("superseded_by", ()),
    )


def not_detectable(reason: str) -> NotDetectable:
    return NotDetectable(reason=reason)


SHORT_NAME = "The name is too short to use as a .env key prefix."
COMMON_WORD = "The name is a common word, so a .env key prefix built from it matches unrelated projects."
