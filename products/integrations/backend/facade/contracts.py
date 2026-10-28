"""Data shapes and errors of the integrations SDK."""

import dataclasses
from collections.abc import Mapping

from posthog.dataclasses import frozen

from products.integrations.backend.facade.enums import AuthType

# A value that `find`, `list` and `exists` can compare a config key with. Equality only.
ConfigValue = str | int | float | bool | None

# A row that holds the typed-in credentials of a warehouse source stores the source type under this
# config key. Only `IntegrationManager.source(kind)` and a reader from `with_source_rows()` read these rows.
SOURCE_MARKER_CONFIG_KEY = "warehouse_source_type"


@frozen
class KindSpec:
    """The auth types of one integration kind. A row without `config["auth_type"]` has the default."""

    label: str
    default: AuthType
    others: frozenset[AuthType] = frozenset()

    @property
    def supported(self) -> frozenset[AuthType]:
        return self.others | {self.default}


@frozen
class IntegrationPatch:
    """A change to one row. `update` and `update_atomically` apply it.

    `errors=None` keeps the stored errors. Pass `""` to clear them.
    """

    config_patch: Mapping[str, object] = dataclasses.field(default_factory=dict)
    config_remove: tuple[str, ...] = ()
    sensitive_config_patch: Mapping[str, object] = dataclasses.field(default_factory=dict)
    sensitive_config_remove: tuple[str, ...] = ()
    errors: str | None = None


@frozen
class IntegrationUsage:
    """One PostHog object that uses an integration row, such as a warehouse source or a workflow."""

    # The kind of object, for example "warehouse_source". The product that reports it chooses the value.
    type: str
    id: str
    name: str


class IntegrationNotFound(LookupError):
    """The row does not exist, belongs to another team, or is not in the scope of the accessor."""


class UnknownIntegrationKind(ValueError):
    """The kind is not in the catalogue, and no product registered it."""


class UnsupportedIntegrationFilter(ValueError):
    """`where` holds a key or a value that the SDK cannot compare.

    The SDK compares named config keys for equality. Anything more needs its own SDK method.
    """


class UnsupportedAuthType(ValueError):
    """The kind does not support the auth type of the write."""


class IntegrationConflict(ValueError):
    """A write hit the unique key (team, kind, external id) of a row.

    `create` raises it for any row with the same key. `upsert` raises it for a row with the same key
    that the accessor cannot write, for example a row with another auth type, or a warehouse source
    row found through a named accessor.
    """


class IntegrationInUse(Exception):
    """`delete` found PostHog objects that use the row."""

    def __init__(self, usages: list[IntegrationUsage]) -> None:
        super().__init__(f"The integration has {len(usages)} usages")
        self.usages = usages
