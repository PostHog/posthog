from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
    SourceFieldSwitchGroupConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sftp import SFTPSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sftp.sftp import (
    AUTH_FAILED_ERROR,
    CONNECTION_FAILED_ERROR,
    DELIMITER_ERROR,
    DIRECTORY_ERROR,
    FORMAT_ERROR,
    NO_FILES_ERROR,
    PATTERN_ERROR,
    PRIVATE_KEY_ERROR,
    SFTPAuth,
    SFTPCredentialsError,
    group_files_by_table,
    list_remote_files,
    parseable_files,
    sftp_connection,
    sftp_source,
    validate_credentials as validate_sftp_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SFTPSource(SimpleSource[SFTPSourceConfig], ValidateDatabaseHostMixin):
    api_docs_url = "https://datatracker.ietf.org/doc/html/draft-ietf-secsh-filexfer-02"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SFTP

    @property
    def connection_host_fields(self) -> list[str]:
        # The port picks which service on the host receives the stored password or key, so editing
        # only the port retargets the credential just as a host change would.
        return ["port"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_FAILED_ERROR: (
                "The SFTP server rejected these credentials. Check the username, and the password or "
                "SSH private key, then reconnect the source."
            ),
            PRIVATE_KEY_ERROR: (
                "The SSH private key couldn't be read. Paste the full private key including the "
                "-----BEGIN and -----END lines, and check the passphrase if the key is encrypted."
            ),
            CONNECTION_FAILED_ERROR: (
                "PostHog couldn't reach the SFTP server. Check the host and port, and that the server "
                "allows connections from the public internet."
            ),
            DIRECTORY_ERROR: (
                "PostHog couldn't read the remote folder. Check that the path exists and that this user "
                "has permission to list it."
            ),
            PATTERN_ERROR: "The file pattern isn't a valid regular expression. Fix the pattern and try again.",
            DELIMITER_ERROR: (
                "The CSV delimiter must be a single character (use \\t for tab-separated files). "
                "Fix the delimiter and try again."
            ),
            FORMAT_ERROR: (
                "PostHog couldn't work out the format of a remote file. Set the file format explicitly, "
                "or restrict the file pattern to .csv, .json, or .jsonl files."
            ),
            NO_FILES_ERROR: (
                "The file behind this table is no longer on the SFTP server. Refresh the source's tables, "
                "or restore the file."
            ),
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SFTP,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="SFTP",
            caption=(
                "Import CSV and JSON files from an SFTP server. PostHog lists the files in the folder you "
                "point it at, including subfolders, and creates one table per file, or one combined table "
                "if you prefer. Every sync reads the files in full, so each table matches what's on the "
                "server right now."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/sftp",
            iconPath="/static/services/sftp.svg",
            keywords=["ssh file transfer", "ssh", "files"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="sftp.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="22",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="Username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="posthog",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_type",
                        label="Authentication type",
                        required=True,
                        defaultValue="password",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Password",
                                value="password",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="password",
                                            label="Password",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="SSH private key",
                                value="ssh_key",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="private_key",
                                            label="Private key",
                                            type=SourceFieldInputConfigType.TEXTAREA,
                                            required=False,
                                            placeholder="-----BEGIN OPENSSH PRIVATE KEY-----",
                                            secret=True,
                                        ),
                                        SourceFieldInputConfig(
                                            name="passphrase",
                                            label="Passphrase (optional)",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="path",
                        label="Folder",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="/incoming",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="file_pattern",
                        label="File pattern (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="\\.csv$",
                        caption=(
                            "A regular expression matched against each file's path inside the folder. Leave "
                            "it empty to import every file."
                        ),
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="file_format",
                        label="File format",
                        required=True,
                        defaultValue="infer",
                        options=[
                            SourceFieldSelectConfigOption(label="Detect from file extension", value="infer"),
                            SourceFieldSelectConfigOption(label="CSV", value="csv"),
                            SourceFieldSelectConfigOption(label="JSON Lines", value="jsonl"),
                            SourceFieldSelectConfigOption(label="JSON", value="json"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="csv_delimiter",
                        label="CSV delimiter (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=",",
                        caption="Use \\t for tab-separated files. Defaults to a comma.",
                        secret=False,
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="combine_files",
                        label="Combine every file into one table?",
                        caption=(
                            "Turn this on when the folder holds files that share the same columns, such as a "
                            "daily export. All matching files land in one table instead of one table per file."
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
            ),
        )

    def _auth(self, config: SFTPSourceConfig) -> SFTPAuth:
        """Keep the unselected authentication type's stored secrets out of the connection."""
        auth = config.auth_type
        if auth.selection == "ssh_key":
            return SFTPAuth(private_key=auth.private_key, passphrase=auth.passphrase)
        return SFTPAuth(password=auth.password)

    def _combined_table_name(self, config: SFTPSourceConfig) -> str | None:
        combine = config.combine_files
        if combine is not None and combine.enabled:
            return combine.table_name
        return None

    def _ensure_host_allowed(self, config: SFTPSourceConfig, team_id: int) -> None:
        """Re-check the host every time we're about to send the stored credential to it."""
        is_host_valid, host_error = self.is_database_host_valid(config.host, team_id)
        if not is_host_valid:
            raise SFTPCredentialsError(f"{CONNECTION_FAILED_ERROR} at {config.host}: {host_error}")

    def validate_credentials(
        self,
        config: SFTPSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_host_valid, host_error = self.is_database_host_valid(config.host, team_id)
        if not is_host_valid:
            return False, host_error

        if not 0 < config.port < 65536:
            return False, "The port must be between 1 and 65535. SFTP servers usually listen on port 22."

        auth = self._auth(config)
        if not auth.password and not auth.private_key:
            return False, "Enter either a password or an SSH private key for this user."

        try:
            validate_sftp_credentials(
                host=config.host,
                port=config.port,
                user=config.user,
                auth=auth,
                path=config.path,
                file_pattern=config.file_pattern,
                configured_format=config.file_format,
                delimiter=config.csv_delimiter,
            )
        except SFTPCredentialsError as e:
            return False, str(e)

        return True, None

    def get_schemas(
        self,
        config: SFTPSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        self._ensure_host_allowed(config, team_id)

        with sftp_connection(
            host=config.host,
            port=config.port,
            user=config.user,
            auth=self._auth(config),
        ) as client:
            files = parseable_files(list_remote_files(client, config.path, config.file_pattern), config.file_format)

        grouped = group_files_by_table(files, self._combined_table_name(config))

        schemas = [SourceSchema(name=name, supports_incremental=False, supports_append=False) for name in grouped]

        if names is not None:
            requested = set(names)
            schemas = [schema for schema in schemas if schema.name in requested]

        return schemas

    def source_for_pipeline(self, config: SFTPSourceConfig, inputs: SourceInputs) -> SourceResponse:
        self._ensure_host_allowed(config, inputs.team_id)

        return sftp_source(
            host=config.host,
            port=config.port,
            user=config.user,
            schema_name=inputs.schema_name,
            auth=self._auth(config),
            path=config.path,
            file_pattern=config.file_pattern,
            configured_format=config.file_format,
            delimiter=config.csv_delimiter,
            combined_table_name=self._combined_table_name(config),
            logger=inputs.logger,
        )
