from typing import TYPE_CHECKING, Optional, cast

from snowflake.connector.errors import DatabaseError, ForbiddenError, HttpError, ProgrammingError

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.exceptions_capture import capture_exception

from products.data_warehouse.backend.facade.api import reconcile_snowflake_schemas
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.snowflake import (
    SnowflakeImplementation,
    get_connection_metadata as get_connection_metadata_snowflake,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SNOWFLAKE_IMPLEMENTATION = SnowflakeImplementation()

# cryptography raises ValueError("Unable to load PEM file ...") when the key-pair private key can't
# be parsed — typically the user pasted the bare base64 DER body without the
# `-----BEGIN/END PRIVATE KEY-----` framing, or a truncated key. The `{action}` placeholder lets each
# call site supply its own context-appropriate verb ("resync." on the sync path, "try again." during
# credential validation) while keeping the guidance text defined once.
_MALFORMED_PEM_MESSAGE = (
    "Your Snowflake key-pair private key could not be read. Paste the full PEM private key including "
    "the -----BEGIN PRIVATE KEY----- and -----END PRIVATE KEY----- lines (not just the base64 body), "
    "then {action}"
)

SnowflakeErrors = {
    "No active warehouse selected in the current session": "No active warehouse is available for this connection. Check that the configured warehouse exists, is running, and that the connecting role has USAGE on it, then try again.",
    "or attempt to login with another role": "Role specified doesn't exist or is not authorized",
    "Incorrect username or password was specified": "Incorrect username or password was specified",
    "This session does not have a current database": "No database is available for this connection. Check that the configured database exists and that the connecting role has USAGE on it, then try again.",
    "Verify the account name is correct": "Can't find an account with the specified account ID",
    "Multi-factor authentication is required for this account": "This Snowflake account requires multi-factor authentication enrollment. Connect with a service user that uses key-pair authentication or is exempt from MFA.",
    # Snowflake error 290404: the login-request endpoint 404s because the account identifier doesn't
    # resolve to a real deployment (wrong/incomplete account id, missing region/cloud segment). The
    # connector raises HttpError rather than the "Verify the account name is correct" OperationalError,
    # so it needs its own entry. The host and port in the message are volatile, so we match "404 Not Found".
    "404 Not Found": "Can't find a Snowflake account with the specified account ID. Please check your account identifier and try again.",
}


@SourceRegistry.register
class SnowflakeSource(SQLSource[SnowflakeSourceConfig]):
    @property
    def get_implementation(self) -> SnowflakeImplementation:
        return _SNOWFLAKE_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SNOWFLAKE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SNOWFLAKE,
            category=DataWarehouseSourceCategory.DATABASES,
            caption="Enter your Snowflake credentials to automatically pull your Snowflake data into the PostHog Data warehouse.",
            iconPath="/static/services/snowflake.png",
            docsUrl="https://posthog.com/docs/cdp/sources/snowflake",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="connection_string",
                        label="Connection string (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="snowflake://user:password@account_id/database/schema?warehouse=COMPUTE_WAREHOUSE&role=ACCOUNTADMIN",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account id",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="snowflake_sample_data",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="warehouse",
                        label="Warehouse",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="COMPUTE_WAREHOUSE",
                        secret=False,
                    ),
                    # the validation for these options happens in validate_credentials
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
                                            name="user",
                                            label="Username",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="User1",
                                            secret=False,
                                        ),
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
                                label="Key pair",
                                value="keypair",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="user",
                                            label="Username",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="User1",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="private_key",
                                            label="Private key",
                                            type=SourceFieldInputConfigType.TEXTAREA,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                        SourceFieldInputConfig(
                                            name="passphrase",
                                            label="Passphrase",
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
                        name="role",
                        label="Role (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="ACCOUNTADMIN",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="schema",
                        label="Schema (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to import all schemas",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "This account has been marked for decommission": "Your Snowflake account has been suspended or trial has ended. Please check your account status.",
            # Snowflake error 000606 (57P03): the session has no active warehouse, so the first query
            # needing compute fails. The connector doesn't fail at connect time even when the configured
            # warehouse is missing/suspended or the role lacks USAGE on it — it just leaves the session
            # warehouse unset. Retrying can never succeed until the customer fixes the grant or warehouse.
            "No active warehouse selected in the current session": "No active warehouse is available for this connection. Check that the configured warehouse exists, is running, and that the connecting role has USAGE on it, then resync.",
            # Snowflake error 090105 (22000): the session has no current database, so the first query
            # that references an unqualified object (our `information_schema` listing query) fails. The
            # connector doesn't fail at connect time when the configured database is missing or the role
            # lacks USAGE on it — it just leaves the session database unset. Retrying can never succeed
            # until the customer fixes the database name or the grant. The query id is volatile, so we
            # match the stable phrase.
            "This session does not have a current database": "No database is available for this connection. Check that the configured database exists and that the connecting role has USAGE on it, then resync.",
            "404 Not Found": None,
            "Your free trial has ended": "Your Snowflake account has been suspended or trial has ended. Please check your account status.",
            "Your account is suspended due to lack of payment method": "Your Snowflake account has been suspended or trial has ended. Please check your account status.",
            # Snowflake error 250001: the user account was disabled by the customer's Snowflake admin
            # (e.g. `ALTER USER ... SET DISABLED = TRUE`). Retrying can never succeed until they re-enable it.
            "User access disabled. Contact your local system administrator": "Your Snowflake user account has been disabled. Please contact your Snowflake administrator to re-enable it, then resync.",
            # Snowflake error 250001 (08001): the user's password has expired. Snowflake requires it
            # to be changed via the web console before any login can succeed, so retrying never works.
            "Specified password has expired": "Your Snowflake password has expired. Please change it in the Snowflake web console (or switch to key-pair authentication), then resync.",
            "MFA authentication is required": None,
            # The account enforces Duo Security multi-factor auth for this user, so the
            # connector's login is rejected (250001 / 08001). An unattended sync can't answer a
            # Duo push, so retrying never succeeds — surface an actionable message instead.
            "Duo Security authentication is denied": "Snowflake rejected the login because multi-factor authentication (Duo Security) is enforced for this user. Automated syncs can't answer an MFA prompt — connect with a service user that uses key-pair authentication or is exempt from MFA.",
            # Snowflake error 250001 (08001): the account requires MFA enrollment, so the login is
            # rejected until the user enrolls via Snowsight. An unattended sync can't complete MFA, so
            # retrying never succeeds. The codes and host in the message are volatile, so we match the
            # stable phrase.
            "Multi-factor authentication is required for this account": "Snowflake rejected the login because this account requires multi-factor authentication enrollment. Automated syncs can't complete MFA — connect with a service user that uses key-pair authentication or is exempt from MFA, then resync.",
            "invalid credentials": "Snowflake authentication failed. Please check your username, password, and account details.",
            "authentication failed": "Snowflake authentication failed. Please check your username, password, and account details.",
            # Snowflake error 250001 (08001): the supplied username or password is wrong, so the
            # connector's login is rejected at connect time. Retrying can never succeed until the
            # customer corrects the credentials. The codes, account id, and host in the message are
            # volatile, so we match on the stable trailing phrase.
            "Incorrect username or password was specified": "Snowflake rejected the login because the username or password is incorrect. Please check your Snowflake username and password (or switch to key-pair authentication), then resync.",
            # Snowflake error 000904 (42000): the table or view we select from references a column
            # that no longer exists — typically a stale view definition or a column dropped/renamed
            # in the source schema. We only run `SELECT ... FROM IDENTIFIER(%s)`, so the bad identifier
            # lives in the customer's object, not in our SQL. Retrying can't fix it until they repair
            # the object or reconfigure the synced columns.
            "invalid identifier": "A Snowflake table or view you're syncing references a column that no longer exists (for example a stale view definition, or a column that was dropped or renamed). Please fix the table or view in Snowflake, or reconfigure the columns selected for this table, then resync.",
            # Snowflake error 250001 (08001): a network policy (IP allowlist) on the customer's account
            # rejects the connection because PostHog's egress IP isn't permitted. Retrying can never
            # succeed until their admin allowlists our IPs, so stop retrying and surface what to do.
            "is not allowed to access Snowflake": "Snowflake rejected the connection because a network policy (IP allowlist) on your account does not permit PostHog's IP address. Ask your Snowflake administrator to add PostHog's egress IP addresses to the network policy allowlist, then resync.",
            # Snowflake error 250001 (08001): key-pair login was rejected because the JWT we signed with
            # the configured private key doesn't match the public key registered on the Snowflake user
            # (rotated/removed key, key assigned to a different user, or the wrong key pasted). Retrying
            # can never succeed until the customer re-registers the matching public key. The host and
            # request id in the message are volatile, so we match the stable phrase.
            "JWT token is invalid": "Snowflake rejected key-pair authentication because the signed token is invalid — the private key you configured doesn't match the public key registered on the Snowflake user (often after a key rotation, or if the public key was never set). Re-register the matching public key on your Snowflake user (ALTER USER ... SET RSA_PUBLIC_KEY), or paste the correct private key here, then resync.",
            # See `_MALFORMED_PEM_MESSAGE`: the key-pair private key can't be parsed, so retrying can
            # never succeed until the user pastes a valid PEM key.
            "Unable to load PEM file": _MALFORMED_PEM_MESSAGE.format(action="resync."),
            # Snowflake error 002003 (SQLSTATE 42S02 for tables / 02000 for schemas): a table or
            # schema the source syncs was dropped or renamed in Snowflake, or the role's grant on it
            # was revoked, after the schema was discovered. The driver raises "<object> does not exist
            # or not authorized" on `SHOW PRIMARY KEYS` / the data query. Retrying can never succeed
            # until the user restores the object or re-grants access. The object name and query id in
            # the message are volatile, so we match on the stable trailing phrase.
            "does not exist or not authorized": "A table or schema this source syncs no longer exists in Snowflake, or your role is no longer authorized to access it. Check that the object still exists and that your Snowflake role has access, then resync.",
            # Raised from the shared `evolve_pyarrow_schema` in `pipelines/pipeline/utils.py`
            # when an integer column's source type was widened (e.g. a narrower NUMBER widened
            # to a larger NUMBER/BIGINT) after the destination table was created with the
            # narrower type. Delta Lake can't widen an existing column in place, so retrying
            # won't help — the table must be reset and fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
            # Snowflake SQL compilation error 002057: a view's declared column list no longer
            # matches the columns its query produces, so the view itself fails to compile. This is
            # a broken object on the source side that retrying can't repair.
            "but view query produces": "A Snowflake view in your source is invalid — the columns it declares no longer match the columns its query returns. Please recreate the view in Snowflake so the two agree, then resync.",
        }

    def reconcile_schema_metadata(
        self,
        source: "ExternalDataSource",
        source_schemas: list[SourceSchema],
        team_id: int,
    ) -> list[str]:
        """Delegates to `reconcile_snowflake_schemas` so direct-query mode also rebuilds DWH tables."""
        return reconcile_snowflake_schemas(source=source, source_schemas=source_schemas, team_id=team_id)

    def get_connection_metadata(
        self, config: SnowflakeSourceConfig, team_id: int, require_ssl: bool = False
    ) -> dict[str, str | None]:
        # `require_ssl` keeps signature parity with Postgres/MySQL; Snowflake transport is always TLS.
        return get_connection_metadata_snowflake(config)

    def validate_credentials(
        self, config: SnowflakeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if config.auth_type.selection == "password" and (not config.auth_type.user or not config.auth_type.password):
            return False, "Missing required parameters: username, password"

        # passphrase is optional if the key they use to auth is not encrypted
        if config.auth_type.selection == "keypair" and (not config.auth_type.user or not config.auth_type.private_key):
            return False, "Missing required parameters: username, private key"

        try:
            self.get_schemas(config, team_id)
        except (ProgrammingError, DatabaseError, ForbiddenError, HttpError) as e:
            error_msg = e.msg or e.raw_msg or ""
            for key, value in SnowflakeErrors.items():
                if key in error_msg:
                    return False, value

            capture_exception(e)
            return False, "Could not connect to Snowflake. Please check all connection details are valid."
        except ValueError as e:
            # A malformed key-pair private key fails to parse in `load_pem_private_key` before we ever
            # reach Snowflake — a user config error, not an unexpected failure worth capturing.
            if "Unable to load PEM file" in str(e):
                return False, _MALFORMED_PEM_MESSAGE.format(action="try again.")
            capture_exception(e)
            return False, "Could not connect to Snowflake. Please check all connection details are valid."
        except Exception as e:
            capture_exception(e)
            return False, "Could not connect to Snowflake. Please check all connection details are valid."

        return True, None
