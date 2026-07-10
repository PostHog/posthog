import datetime as dt
import dataclasses

# Label used by sources whose vendor has no meaningful API versioning. Version strings are
# opaque vendor labels (Stripe date versions, semver, names) — never parsed or ordered.
UNVERSIONED_API_VERSION = "v1"


@dataclasses.dataclass(frozen=True)
class VersionDeprecation:
    """Deprecation metadata for a single supported version of a source's vendor API."""

    version: str
    sunset_at: dt.date | None = None


def resolve_api_version(pinned: str | None, default_version: str) -> str:
    """Resolve a stored version pin to the effective vendor API version.

    A missing pin falls back to the source's default. A present pin is honored verbatim —
    even if the source no longer declares it — because silently moving a customer to another
    version is the failure mode this framework exists to prevent; the vendor API is the real
    validator of the label.
    """
    return pinned or default_version
