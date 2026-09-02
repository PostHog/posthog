import io
import stat
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sftp import (
    SFTPAuthTypeConfig,
    SFTPCombineFilesConfig,
    SFTPSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sftp.settings import FILE_PATH_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.sources.sftp.sftp import (
    AUTH_FAILED_ERROR,
    DELIMITER_ERROR,
    DIRECTORY_ERROR,
    SFTPAuth,
    SFTPCredentialsError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sftp.source import SFTPSource

DIRECTORY_MODE = stat.S_IFDIR | 0o755
FILE_MODE = stat.S_IFREG | 0o644

CONNECTION_TARGET = "products.warehouse_sources.backend.temporal.data_imports.sources.sftp.source.sftp_connection"
TRANSPORT_CONNECTION_TARGET = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.sftp.sftp.sftp_connection"
)


class FakeAttributes:
    def __init__(self, filename: str, st_mode: int = FILE_MODE) -> None:
        self.filename = filename
        self.st_mode = st_mode
        self.st_size = 8
        self.st_mtime = 1_700_000_000


class FakeHandle(io.BytesIO):
    def prefetch(self, file_size: int | None = None) -> None:
        return None


class FakeClient:
    def __init__(
        self,
        tree: dict[str, list[FakeAttributes]],
        contents: dict[str, bytes] | None = None,
        unreadable: set[str] | None = None,
    ) -> None:
        self.tree = tree
        self.contents = contents or {}
        self.unreadable = unreadable or set()

    def listdir_attr(self, path: str) -> list[Any]:
        if path in self.unreadable:
            raise OSError(f"permission denied: {path}")
        if path not in self.tree:
            raise OSError(f"no such directory: {path}")
        return list(self.tree[path])

    def open(self, filename: str, mode: str = "r", bufsize: int = -1) -> FakeHandle:
        return FakeHandle(self.contents[filename])


def make_config(
    auth: SFTPAuthTypeConfig | None = None,
    path: str = "/data",
    port: int = 22,
    file_pattern: str | None = None,
    file_format: str = "infer",
    csv_delimiter: str | None = None,
    combine_files: SFTPCombineFilesConfig | None = None,
) -> SFTPSourceConfig:
    return SFTPSourceConfig(
        host="sftp.example.com",
        user="posthog",
        auth_type=auth or SFTPAuthTypeConfig(selection="password", password="hunter2"),
        path=path,
        port=port,
        file_pattern=file_pattern,
        file_format=cast(Any, file_format),
        csv_delimiter=csv_delimiter,
        combine_files=combine_files,
    )


def make_inputs(schema_name: str = "orders") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


def patched_connection(client: FakeClient, target: str = CONNECTION_TARGET) -> Any:
    connection = patch(target)
    started = connection.start()
    started.return_value.__enter__.return_value = client
    return connection


class TestSFTPSourceConfig:
    def setup_method(self) -> None:
        self.source = SFTPSource()

    def test_port_change_requires_credential_reentry(self) -> None:
        assert self.source.connection_host_fields == ["port"]

    def test_non_retryable_errors_cover_connection_and_auth_failures(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert AUTH_FAILED_ERROR in errors
        assert all(message for message in errors.values())


class TestValidateCredentials:
    def setup_method(self) -> None:
        self.source = SFTPSource()

    @pytest.mark.parametrize(
        ("config", "expected_error"),
        [
            (make_config(port=0), "port must be between"),
            (make_config(port=70000), "port must be between"),
            (make_config(auth=SFTPAuthTypeConfig(selection="password")), "password or an SSH private key"),
            (make_config(auth=SFTPAuthTypeConfig(selection="ssh_key")), "password or an SSH private key"),
        ],
    )
    def test_rejects_incomplete_config_without_connecting(self, config: SFTPSourceConfig, expected_error: str) -> None:
        with patch(CONNECTION_TARGET) as connection:
            is_valid, error = self.source.validate_credentials(config, team_id=1)

        assert is_valid is False
        assert error is not None and expected_error in error
        connection.assert_not_called()

    def test_rejects_an_invalid_delimiter_without_connecting(self) -> None:
        with patch(CONNECTION_TARGET) as connection:
            is_valid, error = self.source.validate_credentials(make_config(csv_delimiter="||"), team_id=1)

        assert is_valid is False
        assert error is not None and DELIMITER_ERROR in error
        connection.assert_not_called()

    def test_rejects_an_unsafe_host(self) -> None:
        with patch.object(SFTPSource, "is_database_host_valid", return_value=(False, "nope")):
            is_valid, error = self.source.validate_credentials(make_config(), team_id=1)

        assert (is_valid, error) == (False, "nope")

    def test_accepts_a_readable_directory(self) -> None:
        connection = patched_connection(
            FakeClient({"/data": [FakeAttributes("orders.csv")]}), TRANSPORT_CONNECTION_TARGET
        )
        try:
            assert self.source.validate_credentials(make_config(), team_id=1) == (True, None)
        finally:
            connection.stop()

    def test_surfaces_a_connection_failure_as_a_message(self) -> None:
        with patch(TRANSPORT_CONNECTION_TARGET, side_effect=SFTPCredentialsError(f"{DIRECTORY_ERROR} '/data'")):
            is_valid, error = self.source.validate_credentials(make_config(), team_id=1)

        assert is_valid is False
        assert error is not None and DIRECTORY_ERROR in error


class TestGetSchemas:
    def setup_method(self) -> None:
        self.source = SFTPSource()
        self.client = FakeClient(
            {
                "/data": [
                    FakeAttributes("orders.csv"),
                    FakeAttributes("2024", st_mode=DIRECTORY_MODE),
                    FakeAttributes("notes.md"),
                ],
                "/data/2024": [FakeAttributes("orders.csv")],
            }
        )

    def test_one_full_refresh_table_per_file_with_a_recognized_format(self) -> None:
        connection = patched_connection(self.client)
        try:
            schemas = self.source.get_schemas(make_config(), team_id=1)
        finally:
            connection.stop()

        # notes.md has no format we can parse, so discovery doesn't offer it as a table.
        assert [schema.name for schema in schemas] == ["2024_orders", "orders"]
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_an_explicit_format_offers_every_matched_file(self) -> None:
        connection = patched_connection(self.client)
        try:
            schemas = self.source.get_schemas(make_config(file_format="csv"), team_id=1)
        finally:
            connection.stop()

        assert [schema.name for schema in schemas] == ["2024_orders", "notes", "orders"]

    def test_pattern_narrows_the_tables(self) -> None:
        connection = patched_connection(self.client)
        try:
            schemas = self.source.get_schemas(make_config(file_pattern=r"\.csv$"), team_id=1)
        finally:
            connection.stop()

        assert [schema.name for schema in schemas] == ["2024_orders", "orders"]

    def test_combine_files_produces_a_single_table(self) -> None:
        connection = patched_connection(self.client)
        try:
            schemas = self.source.get_schemas(
                make_config(combine_files=SFTPCombineFilesConfig(table_name="All orders", enabled=True)),
                team_id=1,
            )
        finally:
            connection.stop()

        assert [schema.name for schema in schemas] == ["all_orders"]

    def test_disabled_combine_files_keeps_one_table_per_file(self) -> None:
        connection = patched_connection(self.client)
        try:
            schemas = self.source.get_schemas(
                make_config(combine_files=SFTPCombineFilesConfig(table_name="All orders", enabled=False)),
                team_id=1,
            )
        finally:
            connection.stop()

        assert [schema.name for schema in schemas] == ["2024_orders", "orders"]

    def test_filters_by_requested_names(self) -> None:
        connection = patched_connection(self.client)
        try:
            schemas = self.source.get_schemas(make_config(), team_id=1, names=["orders"])
        finally:
            connection.stop()

        assert [schema.name for schema in schemas] == ["orders"]

    def test_lists_no_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is False
        assert self.source.get_documented_tables() == []


class TestSourceForPipeline:
    def setup_method(self) -> None:
        self.source = SFTPSource()

    def test_passes_the_configured_format_and_credentials_through(self) -> None:
        config = make_config(
            auth=SFTPAuthTypeConfig(selection="ssh_key", private_key="key", passphrase="phrase"),
            file_format="csv",
            csv_delimiter="\\t",
            file_pattern=r"\.tsv$",
            combine_files=SFTPCombineFilesConfig(table_name="orders", enabled=True),
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.sftp.source.sftp_source"
        ) as source_fn:
            self.source.source_for_pipeline(config, make_inputs("orders"))

        kwargs = source_fn.call_args.kwargs
        assert kwargs["auth"] == SFTPAuth(private_key="key", passphrase="phrase")
        assert kwargs["configured_format"] == "csv"
        assert kwargs["delimiter"] == "\\t"
        assert kwargs["file_pattern"] == r"\.tsv$"
        assert kwargs["combined_table_name"] == "orders"
        assert kwargs["schema_name"] == "orders"

    def test_reads_the_rows_of_the_requested_table(self) -> None:
        client = FakeClient(
            {"/data": [FakeAttributes("orders.csv"), FakeAttributes("refunds.csv")]},
            contents={"/data/orders.csv": b"id,total\n1,10\n", "/data/refunds.csv": b"id,total\n2,20\n"},
        )

        response = self.source.source_for_pipeline(make_config(), make_inputs("refunds"))

        connection = patched_connection(client, TRANSPORT_CONNECTION_TARGET)
        try:
            rows = [row for chunk in cast(Any, response.items()) for row in chunk]
        finally:
            connection.stop()

        assert response.name == "refunds"
        assert [(row["id"], row["total"], row[FILE_PATH_COLUMN]) for row in rows] == [("2", "20", "refunds.csv")]


class TestHostRechecks:
    """A stored credential must not be sent to a host that stopped being reachable-safe after create."""

    def setup_method(self) -> None:
        self.source = SFTPSource()

    @pytest.mark.parametrize("method", ["get_schemas", "source_for_pipeline"])
    def test_rejects_an_unsafe_host_before_connecting(self, method: str) -> None:
        with patch.object(SFTPSource, "is_database_host_valid", return_value=(False, "internal IP")):
            with (
                patch(CONNECTION_TARGET) as connection,
                patch(
                    "products.warehouse_sources.backend.temporal.data_imports.sources.sftp.source.sftp_source"
                ) as source_fn,
            ):
                with pytest.raises(SFTPCredentialsError, match="internal IP"):
                    if method == "get_schemas":
                        self.source.get_schemas(make_config(), team_id=1)
                    else:
                        self.source.source_for_pipeline(make_config(), make_inputs())

        connection.assert_not_called()
        source_fn.assert_not_called()
