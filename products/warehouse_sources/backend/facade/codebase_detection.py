"""How the wizard tells that a codebase uses a source, declared by each source as `codebase_detection`.

The wizard projects these declarations into the detector registry it scans codebases with. See
`products/wizard/backend/tool_catalog/`.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import TypedDict, Unpack, cast

from posthog.dataclasses import frozen
from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldConfig,
    SourceFieldCredentialAccountSelectConfig,
    SourceFieldFileUploadConfig,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)


class Ecosystem(StrEnum):
    NPM = "npm"
    # Lowercase, with `_` replaced by `-`, the way the wizard normalizes Python dependency names.
    PYPI = "pypi"
    CARGO = "cargo"
    COCOAPODS = "cocoapods"
    COMPOSER = "composer"
    # Module path without a trailing `/vN` major-version element.
    GO = "go"
    HEX = "hex"
    # `group:artifact` coordinates.
    MAVEN = "maven"
    PUB = "pub"
    RUBYGEMS = "rubygems"
    # Package URL without scheme or `.git`, lowercase, e.g. `github.com/getsentry/sentry-cocoa`.
    SWIFTPM = "swiftpm"


@frozen
class Detection:
    # Anchored regexes matched against `.env` key names. The wizard compiles them as JavaScript
    # regexes, so they must stay in the subset both engines read the same way.
    env_key_patterns: tuple[str, ...]
    # A host matches itself and its subdomains.
    script_hosts: tuple[str, ...]
    packages: Mapping[Ecosystem, tuple[str, ...]]
    alternative_to: tuple[ProductKey, ...]
    # Kinds that reach the same data through a more specific connector. When one of them also
    # matches, the wizard drops this one so the data is not imported twice.
    superseded_by: tuple[str, ...]


@frozen
class NotDetectable:
    """No SDK, documented .env key or script host identifies the vendor in code."""


NOT_DETECTABLE = NotDetectable()


class _Signals(TypedDict, total=False):
    env: tuple[str, ...]
    script_hosts: tuple[str, ...]
    npm: tuple[str, ...]
    pypi: tuple[str, ...]
    cargo: tuple[str, ...]
    cocoapods: tuple[str, ...]
    composer: tuple[str, ...]
    go: tuple[str, ...]
    hex: tuple[str, ...]
    maven: tuple[str, ...]
    pub: tuple[str, ...]
    rubygems: tuple[str, ...]
    swiftpm: tuple[str, ...]
    alternative_to: tuple[ProductKey, ...]
    superseded_by: tuple[str, ...]


def detect(**signals: Unpack[_Signals]) -> Detection:
    # The package keyword names match the Ecosystem values, so a lookup by value finds them.
    by_name = cast(Mapping[str, tuple[str, ...]], signals)
    return Detection(
        env_key_patterns=signals.get("env", ()),
        script_hosts=signals.get("script_hosts", ()),
        packages={ecosystem: by_name[ecosystem.value] for ecosystem in Ecosystem if by_name.get(ecosystem.value)},
        alternative_to=signals.get("alternative_to", ()),
        superseded_by=signals.get("superseded_by", ()),
    )


_UI_ONLY_FIELDS = (
    SourceFieldOauthConfig,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldCredentialAccountSelectConfig,
    SourceFieldFileUploadConfig,
)


def _option_requires_ui(option: SourceFieldSelectConfigOption) -> bool:
    fields = option.fields or []
    # An option's credential field is often marked optional, but choosing the option means filling it.
    return any(isinstance(field, _UI_ONLY_FIELDS) for field in fields) or fields_require_ui(fields)


def fields_require_ui(fields: Sequence[SourceFieldConfig]) -> bool:
    """Whether every way through a source's form needs OAuth, a file upload or an account picker."""
    for field in fields:
        if isinstance(field, _UI_ONLY_FIELDS) and field.required is not False:
            return True
        if (
            isinstance(field, SourceFieldSelectConfig)
            and field.required
            and field.options
            and all(_option_requires_ui(option) for option in field.options)
        ):
            return True
    return False
