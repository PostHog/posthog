"""Source of truth for the data warehouse source-config contract.

Every import source describes its setup form with these models. The wizard endpoint and
the public catalog endpoint serialize them, and the frontend types are generated from
this module by drf-spectacular and Orval (``hogli build:openapi``). Change a model here
and rerun that command; do not hand-write the TypeScript counterparts.

Field names stay camelCase because they cross the wire to the frontend unchanged.
"""

from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel
from pydantic.json_schema import WithJsonSchema

from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

__all__ = [
    "DataWarehouseSourceCategory",
    "ReleaseStatus",
    "SourceConfig",
    "SourceConfigMapResponse",
    "SourceConfigResponse",
    "SourceDocumentedTable",
    "SourceFieldConfig",
    "SourceFieldFileUploadConfig",
    "SourceFieldFileUploadJsonFormatConfig",
    "SourceFieldInputConfig",
    "SourceFieldInputConfigType",
    "SourceFieldOauthAccountSelectConfig",
    "SourceFieldOauthConfig",
    "SourceFieldSSHTunnelConfig",
    "SourceFieldSelectConfig",
    "SourceFieldSelectConfigConverter",
    "SourceFieldSelectConfigOption",
    "SourceFieldSwitchGroupConfig",
    "SourceVersionDeprecation",
    "SuggestedTable",
]


def _require_type_field(schema: dict[str, Any]) -> None:
    """Keep the `type` discriminant required even though it has a default.

    Pydantic drops defaulted fields from `required`. The generated TS would then mark
    `type` optional and could not narrow the field-config union on it.
    """
    if "type" not in schema["properties"]:
        return
    required = {*schema.get("required", []), "type"}
    schema["required"] = [name for name in schema["properties"] if name in required]


_WIRE_MODEL_CONFIG = ConfigDict(extra="forbid", json_schema_extra=_require_type_field)


class DataWarehouseSourceCategory(StrEnum):
    DATABASES = "Databases"
    FILE_STORAGE = "File storage"
    ADVERTISING = "Advertising"
    MARKETING___EMAIL = "Marketing & email"
    CRM = "CRM"
    SALES = "Sales"
    CUSTOMER_SUPPORT = "Customer support"
    PAYMENTS___BILLING = "Payments & billing"
    FINANCE___ACCOUNTING = "Finance & accounting"
    ANALYTICS = "Analytics"
    ENGINEERING___MONITORING = "Engineering & monitoring"
    PRODUCTIVITY = "Productivity"
    HR___RECRUITING = "HR & recruiting"
    COMMUNICATION = "Communication"
    E_COMMERCE = "E-commerce"


class ReleaseStatus(StrEnum):
    ALPHA = "alpha"
    BETA = "beta"
    GA = "ga"


class SourceFieldInputConfigType(StrEnum):
    TEXT = "text"
    EMAIL = "email"
    SEARCH = "search"
    URL = "url"
    PASSWORD = "password"
    TIME = "time"
    NUMBER = "number"
    TEXTAREA = "textarea"


class SourceFieldSelectConfigConverter(StrEnum):
    STR_TO_INT = "str_to_int"
    STR_TO_BOOL = "str_to_bool"
    STR_TO_OPTIONAL_INT = "str_to_optional_int"


class SourceFieldSSHTunnelConfig(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    label: str
    name: str
    type: Literal["ssh-tunnel"] = "ssh-tunnel"


class SourceFieldOauthConfig(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    kind: str
    label: str
    name: str
    required: bool
    requiredScopes: str | None = None
    type: Literal["oauth"] = "oauth"


class SourceFieldOauthAccountSelectConfig(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    caption: str | None = None
    hidden: bool | None = Field(
        default=None,
        description=(
            "Keep the field in the config tree (so its value parses and survives"
            " job_inputs redaction) without rendering it in the source form. Used for"
            " legacy fields that a newer field supersedes."
        ),
    )
    integrationField: str = Field(
        ...,
        description=("Name of the OAuth integration id field this account selector reads from."),
    )
    integrationKind: str = Field(
        ...,
        description="Integration kind to validate and route the account fetch through.",
    )
    label: str
    multiple: bool | None = Field(
        default=None,
        description=("Allow selecting multiple values; the field's payload value becomes string[]."),
    )
    name: str
    placeholder: str | None = None
    required: bool | None = None
    type: Literal["oauth-account-select"] = "oauth-account-select"


class SourceFieldInputConfig(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    caption: str | None = None
    label: str
    name: str
    placeholder: str
    required: bool
    secret: bool = Field(
        ...,
        description=(
            "Marks this field as containing sensitive data. The value is stripped from"
            " API responses regardless of the rendering `type` (so a multi-line PEM"
            " blob can use `textarea` and still be redacted). Required: source authors"
            " must explicitly classify every field."
        ),
    )
    # Spelled out as a `Literal` of the enum members because pydantic infers a
    # discriminated union only from `Literal` discriminator fields. The stored value is
    # still a `SourceFieldInputConfigType` member.
    type: Literal[
        SourceFieldInputConfigType.TEXT,
        SourceFieldInputConfigType.EMAIL,
        SourceFieldInputConfigType.SEARCH,
        SourceFieldInputConfigType.URL,
        SourceFieldInputConfigType.PASSWORD,
        SourceFieldInputConfigType.TIME,
        SourceFieldInputConfigType.NUMBER,
        SourceFieldInputConfigType.TEXTAREA,
    ]


class SourceFieldFileUploadJsonFormatConfig(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    format: Literal[".json"] = ".json"
    keys: str | list[str]


class SourceFieldFileUploadConfig(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    fileFormat: SourceFieldFileUploadJsonFormatConfig
    label: str
    name: str
    required: bool
    type: Literal["file-upload"] = "file-upload"


class SourceFieldSelectConfigOption(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    fields: list["SourceFieldConfig"] | None = None
    label: str
    value: str


class SourceFieldSelectConfig(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    caption: str | None = None
    converter: SourceFieldSelectConfigConverter | None = None
    defaultValue: str
    label: str
    multiple: bool | None = Field(
        default=None,
        description=("Allow selecting multiple values; the field's payload value becomes string[]."),
    )
    name: str
    options: list[SourceFieldSelectConfigOption]
    required: bool
    type: Literal["select"] = "select"


class SourceFieldSwitchGroupConfig(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    caption: str | None = None
    default: str | float | bool
    fields: list["SourceFieldConfig"]
    label: str
    name: str
    type: Literal["switch-group"] = "switch-group"


# `SourceFieldInputConfig` accepts several `type` values and the other variants accept
# one each. Pydantic maps every value to its variant, so the generated schema narrows on
# `type` instead of making the reader try each variant in turn.
SourceFieldConfig = Annotated[
    Union[
        SourceFieldInputConfig,
        SourceFieldSwitchGroupConfig,
        SourceFieldSelectConfig,
        SourceFieldOauthConfig,
        SourceFieldOauthAccountSelectConfig,
        SourceFieldFileUploadConfig,
        SourceFieldSSHTunnelConfig,
    ],
    Field(discriminator="type"),
]

SourceFieldSelectConfigOption.model_rebuild()
SourceFieldSelectConfig.model_rebuild()
SourceFieldSwitchGroupConfig.model_rebuild()


# Pydantic publishes an enum as its own schema component, which would put a second copy
# of the source type list next to the one the DRF serializers already publish. Emitting
# the values inline instead lets drf-spectacular's enum post-processing match them by
# hash and point both at the single `ExternalDataSourceTypeEnum` component.
InlinedExternalDataSourceType = Annotated[
    ExternalDataSourceType,
    WithJsonSchema({"type": "string", "enum": ExternalDataSourceType.values}),
]


class SuggestedTable(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    table: str
    tooltip: str | None = None


class SourceConfig(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    caption: str | None = None
    category: DataWarehouseSourceCategory | None = Field(
        default=None,
        description=(
            "Catalog bucket this source is grouped under in the new-source wizard."
            " Optional at the type level so partial/in-progress sources don't break,"
            " but every registered source must set one (enforced by a test)."
        ),
    )
    disabledReason: str | None = None
    docsUrl: str | None = None
    existingSource: bool | None = None
    featureFlag: str | None = None
    featured: bool | None = Field(
        default=False,
        description=("Whether this source should be prominently displayed in onboarding flows"),
    )
    fields: list[SourceFieldConfig]
    iconClassName: str | None = None
    iconPath: str
    keywords: list[str] | None = Field(
        default=None,
        description=(
            "Extra search terms (alternate spellings, acronyms) for the catalog search,"
            ' e.g. GoogleAnalytics → ["ga4", "ga"]. Matched alongside'
            " name/label/category."
        ),
    )
    label: str | None = None
    name: InlinedExternalDataSourceType
    permissionsCaption: str | None = None
    releaseStatus: ReleaseStatus | None = None
    suggestedTables: list[SuggestedTable] | None = Field(
        default=[],
        description="Tables to suggest enabling, with optional tooltip explaining why",
    )
    supportsColumnSelection: bool | None = Field(
        default=False,
        description=(
            "Whether the source-creation wizard should expose the per-column projection"
            " picker. Mirrors `SQLSource.supports_column_selection` so the wizard"
            " doesn't show a picker for drivers that ignore `enabled_columns` at sync"
            " time."
        ),
    )
    unreleasedSource: bool | None = None
    webhookFields: list[SourceFieldConfig] | None = None
    webhookManualOnly: bool | None = Field(
        default=None,
        description=(
            "If true, the source does not support automatic webhook registration via"
            " API (e.g. Slack, where the user must paste the URL into the source's app"
            " settings). Adjusts the setup UI copy to avoid promising automatic"
            " registration."
        ),
    )
    webhookSetupCaption: str | None = None


class SourceVersionDeprecation(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    version: str
    sunsetAt: str | None = Field(
        default=None,
        description="ISO date the vendor stops serving this version, or null when no date is announced.",
    )


class SourceDocumentedTable(BaseModel):
    model_config = _WIRE_MODEL_CONFIG
    name: str
    label: str
    description: str | None = None
    sync_methods: list[str]
    incremental_fields: list[str]
    primary_keys: list[str]


class SourceConfigResponse(SourceConfig):
    """A `SourceConfig` plus the runtime metadata the two catalog endpoints add per source."""

    supportsColumnSelection: bool = Field(
        ...,
        description=(
            "Whether the source-creation wizard should expose the per-column projection"
            " picker. Mirrors `SQLSource.supports_column_selection` so the wizard"
            " doesn't show a picker for drivers that ignore `enabled_columns` at sync"
            " time."
        ),
    )
    versions: list[str] = Field(..., description="Vendor API version labels this source supports.")
    defaultVersion: str = Field(..., description="Version used when a source instance pins none.")
    apiDocsUrl: str | None = Field(
        default=None,
        description="Vendor API docs or changelog URL, or null when the vendor publishes none.",
    )
    deprecatedVersions: list[SourceVersionDeprecation]
    tables: list[SourceDocumentedTable] | None = Field(
        default=None,
        description=(
            "Credential-free documented table catalog, empty for SQL and file sources"
            " with user-defined schemas. The public endpoint sets it; the wizard omits"
            " it to keep its payload small."
        ),
    )


class SourceConfigMapResponse(RootModel[dict[str, SourceConfigResponse]]):
    """Map of source type identifier to its config, as both catalog endpoints return it."""

    root: dict[str, SourceConfigResponse]
