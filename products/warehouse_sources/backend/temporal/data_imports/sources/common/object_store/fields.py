from typing import Protocol, cast

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSelectConfigOption,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    DiscoveryOptions,
    FileFormatChoice,
)

FEATURE_FLAG = "dwh-object-storage-sources"
KEYWORDS = ["bucket", "csv", "parquet", "delta lake"]


class _CombineFilesConfig(Protocol):
    @property
    def table_name(self) -> str: ...
    @property
    def enabled(self) -> bool: ...


class FileOptionsConfig(Protocol):
    """The settings every object storage source's generated config carries."""

    @property
    def file_pattern(self) -> str | None: ...
    @property
    def file_format(self) -> FileFormatChoice: ...
    @property
    def csv_allow_double_quotes(self) -> bool: ...
    @property
    def combine_files(self) -> _CombineFilesConfig | None: ...


def discovery_options_from(config: FileOptionsConfig) -> DiscoveryOptions:
    combine = config.combine_files
    return DiscoveryOptions(
        file_format=config.file_format,
        file_pattern=(config.file_pattern or "").strip() or None,
        allow_double_quotes=config.csv_allow_double_quotes,
        combined_table_name=combine.table_name if combine is not None and combine.enabled else None,
    )


def source_caption(store: str) -> str:
    return (
        f"Import CSV, JSON Lines and Parquet files, and Delta Lake tables, from {store}. PostHog creates one "
        "table per folder, one per file at the top of the folder you choose, and one per Delta table. A full "
        "refresh reads every file again, so the table matches the files. An incremental or append-only sync "
        "reads only new and changed files, and keeps the rows of files you delete."
    )


def folder_fields(container: str) -> list[FieldType]:
    """The folder and file pattern fields. `container` is the provider's word for a bucket."""
    return cast(
        list[FieldType],
        [
            SourceFieldInputConfig(
                name="path",
                label="Folder (optional)",
                type=SourceFieldInputConfigType.TEXT,
                required=False,
                placeholder="exports/",
                caption=f"Leave it empty to import from the whole {container}.",
                secret=False,
            ),
            SourceFieldInputConfig(
                name="file_pattern",
                label="File pattern (optional)",
                type=SourceFieldInputConfigType.TEXT,
                required=False,
                placeholder="*.parquet",
                caption=(
                    "A glob matched against each file's path inside the folder, where * also matches "
                    "across folders. Leave it empty to import every file."
                ),
                secret=False,
            ),
        ],
    )


def file_option_fields() -> list[FieldType]:
    return cast(
        list[FieldType],
        [
            SourceFieldSelectConfig(
                name="file_format",
                label="File format",
                required=True,
                defaultValue="infer",
                options=[
                    SourceFieldSelectConfigOption(label="Detect from file extension", value="infer"),
                    SourceFieldSelectConfigOption(label="CSV with a header row", value="csv"),
                    SourceFieldSelectConfigOption(label="CSV without a header row", value="csv_no_header"),
                    SourceFieldSelectConfigOption(label="JSON Lines", value="jsonl"),
                    SourceFieldSelectConfigOption(label="Parquet", value="parquet"),
                    SourceFieldSelectConfigOption(label="Delta Lake", value="delta"),
                ],
            ),
            SourceFieldSelectConfig(
                name="csv_allow_double_quotes",
                label="Do double quotes enclose CSV values?",
                required=True,
                defaultValue="true",
                converter=SourceFieldSelectConfigConverter.STR_TO_BOOL,
                options=[
                    SourceFieldSelectConfigOption(label="Yes", value="true"),
                    SourceFieldSelectConfigOption(label="No, treat them as plain text", value="false"),
                ],
            ),
            SourceFieldSwitchGroupConfig(
                name="combine_files",
                label="Combine every file into one table?",
                caption=(
                    "Turn this on when the folder holds files that share the same columns, such as a "
                    "daily export. Delta tables still get a table each."
                ),
                default=False,
                fields=cast(
                    list[FieldType],
                    [
                        SourceFieldInputConfig(
                            name="table_name",
                            label="Table name",
                            type=SourceFieldInputConfigType.TEXT,
                            required=True,
                            placeholder="orders",
                            secret=False,
                        ),
                    ],
                ),
            ),
        ],
    )


def text_field(name: str, label: str, placeholder: str, caption: str | None = None) -> FieldType:
    return SourceFieldInputConfig(
        name=name,
        label=label,
        type=SourceFieldInputConfigType.TEXT,
        required=True,
        placeholder=placeholder,
        caption=caption,
        secret=False,
    )


def secret_field(name: str, label: str, caption: str | None = None) -> FieldType:
    return SourceFieldInputConfig(
        name=name,
        label=label,
        type=SourceFieldInputConfigType.PASSWORD,
        required=True,
        placeholder="",
        caption=caption,
        secret=True,
    )
