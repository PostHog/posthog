from collections.abc import Mapping
from enum import StrEnum

from posthog.dataclasses import frozen
from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class Ecosystem(StrEnum):
    NPM = "npm"
    # Names are normalized the way the wizard's Python parsers emit them: lowercase, `_` → `-`.
    PYPI = "pypi"
    RUBYGEMS = "rubygems"
    COMPOSER = "composer"
    HEX = "hex"
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
    # The wizard opens the app's pre-filled new-source flow in the browser.
    DEEP_LINK = "deep-link"


class ToolOrigin(StrEnum):
    CURATED = "curated"
    # Generated from the source type name, so its signals are a guess until someone curates it.
    DERIVED = "derived"


@frozen
class ToolSignals:
    packages: Mapping[Ecosystem, tuple[str, ...]]
    # Anchored regex sources matched against `.env` key names. The wizard compiles them as
    # JavaScript regexes, so they must stay in the subset both engines read the same way.
    env_key_patterns: tuple[str, ...]
    # A host matches itself and any of its subdomains.
    script_hosts: tuple[str, ...]


@frozen
class Tool:
    kind: str
    label: str
    origin: ToolOrigin
    signals: ToolSignals
    warehouse_source_type: ExternalDataSourceType | None
    # None for a tool the wizard only detects and reports, never offers as a source.
    wizard_setup_mode: WizardSetupMode | None
    competes_with: tuple[ProductKey, ...]
    # The wizard stamps `wizard_ai_sdk_detected` on the organization only for these.
    llm: bool
    # Kinds that reach the same data through a more specific connector. When one of them
    # also matches, the wizard drops this tool so the data is not imported twice.
    superseded_by: tuple[str, ...]
