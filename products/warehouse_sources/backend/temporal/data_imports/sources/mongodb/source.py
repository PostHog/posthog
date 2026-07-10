from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MongoDBSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.mongo import (
    DATABASE_NAME_REQUIRED_ERROR,
    _parse_connection_string,
    filter_mongo_incremental_fields,
    get_collection_names,
    get_leading_index_keys,
    get_schemas as get_mongo_schemas,
    mongo_client,
    mongo_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MONGO_UNREACHABLE_MESSAGE = (
    "Could not reach your MongoDB cluster. Check that the cluster is running and that PostHog's "
    "IP addresses are allowlisted in your database's network access settings."
)

_MONGO_UNESCAPED_CREDENTIALS_MESSAGE = (
    "Your MongoDB connection string is invalid: the username and password must be percent-encoded "
    "per RFC 3986. Escape any reserved characters (e.g. : / ? # [ ] @ %) in your credentials — for "
    "example with urllib.parse.quote_plus — and update the connection string."
)

_MONGO_ATLAS_SQL_MESSAGE = (
    "This connection string points at a MongoDB Atlas SQL / Data Federation endpoint "
    "(its host ends in .query.mongodb.net), which PostHog can't import from — those endpoints "
    "are served by a query proxy for the Atlas SQL ODBC/JDBC drivers, not the standard MongoDB "
    "driver. Use your regular cluster connection string (e.g. mongodb+srv://...mongodb.net) instead."
)

_MONGO_HOST_UNRESOLVED_MESSAGE = (
    "The MongoDB host could not be resolved. Check that the cluster address in your connection "
    "string is spelled correctly."
)

_MONGO_AUTHENTICATION_FAILED_MESSAGE = (
    "MongoDB authentication failed. Please check the username and password for this source."
)

_MONGO_NOT_AUTHORIZED_MESSAGE = (
    "PostHog connected to MongoDB, but this user isn't authorized to list collections on the "
    "database. Grant the user a read role on the database (e.g. read or readAnyDatabase) and try again."
)

_MONGO_CONNECT_FAILED_MESSAGE = (
    "Could not connect to your MongoDB database. Check your connection string and credentials, then try again."
)

# Connection succeeded but nothing importable came back. This is usually a wrong-database or
# permission problem rather than a genuinely empty database: a connection string ending in /admin
# or /test lands on an empty system database, and a user without read access sees no collections.
_MONGO_NO_COLLECTIONS_MESSAGE = (
    "PostHog connected to MongoDB but found no collections in the selected database. Check that "
    "your connection string points at the database that holds your data (a string ending in /admin "
    "or /test connects to an empty system database) or set the Database name field, and make sure "
    "your user has read access to that database's collections."
)

# Substrings pymongo embeds in ServerSelectionTimeoutError when the OS can't resolve the host.
_DNS_RESOLUTION_FAILURE_MARKERS = (
    "No address associated with hostname",
    "nodename nor servname provided",
    "Name or service not known",
    "Temporary failure in name resolution",
)


@SourceRegistry.register
class MongoDBSource(SimpleSource[MongoDBSourceConfig], ValidateDatabaseHostMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONGODB

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        auth_failed_msg = _MONGO_AUTHENTICATION_FAILED_MESSAGE
        return {
            "The DNS query name does not exist": None,
            # pymongo raises InvalidURI("Username and password must be escaped according to RFC 3986,
            # use urllib.parse.quote_plus") before any network call when the credentials in the
            # connection string contain unescaped reserved characters (e.g. ':', '/', '@', '%' in the
            # password). The same RFC-3986 hint also appears on the "Port contains non-digit characters"
            # variant, which is the same unescaped-credential mistake. This is a malformed connection
            # string the user must fix — we can't safely percent-encode it ourselves because the
            # reserved characters are ambiguous with the URI's own delimiters — so retrying never
            # recovers. Match the stable RFC-3986 fragment, not the volatile surrounding text.
            "must be escaped according to RFC 3986": _MONGO_UNESCAPED_CREDENTIALS_MESSAGE,
            # pymongo raises OperationFailure with codeName 'AuthenticationFailed' (code 18) and
            # errmsg 'Authentication failed.' when the credentials are wrong. Non-retryable error
            # matching is case-sensitive, so the previous lowercase "authentication failed" never
            # matched the real message — key off the stable codeName and the capitalised message.
            "AuthenticationFailed": auth_failed_msg,
            "Authentication failed": auth_failed_msg,
            # MongoDB Atlas reports bad credentials differently from self-hosted MongoDB: instead of
            # codeName 'AuthenticationFailed' (code 18) it raises OperationFailure with errmsg
            # 'bad auth : authentication failed' and codeName 'AtlasError' (code 8000). The lowercase
            # 'authentication failed' here doesn't match the capitalised entries above (matching is
            # case-sensitive), so key off the stable Atlas-specific 'bad auth' prefix.
            "bad auth": auth_failed_msg,
            # pymongo raises OperationFailure with codeName 'Unauthorized' (code 13) and errmsg
            # 'not authorized on <db> to execute command ...' when the user authenticates but lacks
            # a read role on the database. str(e) appends the full server response (clusterTime,
            # signature, BSON ids) via pymongo's _format_detailed_error, so the raw text must never
            # reach the user — match the stable 'not authorized' fragment. Granting permission is a
            # config change the user must make, so this never recovers on retry.
            "not authorized": _MONGO_NOT_AUTHORIZED_MESSAGE,
            "SSL handshake failed": None,
            # Atlas SQL / Data Federation endpoints live under *.query.mongodb.net and are served by
            # a query proxy the standard MongoDB driver can't drive: the handshake is closed, the
            # topology never leaves Unknown, and server selection times out (ServerSelectionTimeoutError,
            # frequently "connection closed"). This is a wrong-endpoint misconfiguration — the importer
            # needs a regular cluster connection string — so retrying never recovers. The host suffix
            # is the stable signal here, and it must be matched before the generic "Topology Description:"
            # entry below so Atlas SQL users get the wrong-endpoint message rather than the allowlist one.
            "query.mongodb.net": _MONGO_ATLAS_SQL_MESSAGE,
            # pymongo raises ServerSelectionTimeoutError when it can't select a usable cluster node
            # for the whole selection timeout. The reason varies — "No servers found yet" / "No
            # replica set members found yet" when nothing was ever discovered, or a per-server
            # "<host>: connection closed ... error=AutoReconnect(...)" when a host resolves but every
            # connection attempt is dropped for the entire window. All of these carry the
            # "Topology Description:" suffix that only ServerSelectionTimeoutError emits, so we key
            # off that single marker. On a managed cluster this is a persistent connectivity problem
            # — the worker IP isn't allowlisted, the cluster is paused/decommissioned, or the
            # connection string points at an endpoint the driver can't speak to — not a momentary
            # blip, so retrying the job won't recover it. A transient mid-sync drop surfaces
            # differently (a bare AutoReconnect / NetworkTimeout with no topology description) and
            # stays retryable.
            "Topology Description:": _MONGO_UNREACHABLE_MESSAGE,
        }

    def get_schemas(
        self,
        config: MongoDBSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        mongo_schemas = get_mongo_schemas(config, team_id=team_id, names=names)

        connection_params = _parse_connection_string(config.connection_string, config.database_name)
        leading_keys_by_collection: dict[str, set[str] | None] = {}
        with mongo_client(config.connection_string, team_id=team_id) as client:
            db = client[connection_params["database"]]
            filtered_results = [
                (collection_name, filter_mongo_incremental_fields(columns, db[collection_name]))
                for collection_name, columns in mongo_schemas.items()
            ]
            for collection_name in mongo_schemas:
                leading_keys_by_collection[collection_name] = get_leading_index_keys(db[collection_name])

        return [
            SourceSchema(
                name=name,
                supports_incremental=len(incremental_fields) > 0,
                supports_append=len(incremental_fields) > 0,
                incremental_fields=[
                    {
                        "label": field_name,
                        "type": field_type,
                        "field": field_name,
                        "field_type": field_type,
                        "is_indexed": (
                            True
                            if leading_keys_by_collection.get(name) is None
                            else field_name in (leading_keys_by_collection.get(name) or set())
                        ),
                    }
                    for field_name, field_type in incremental_fields
                ],
            )
            for name, incremental_fields in filtered_results
        ]

    def validate_credentials(
        self, config: MongoDBSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

        try:
            connection_params = _parse_connection_string(config.connection_string, config.database_name)
        except:
            return False, "Invalid connection string"

        if not connection_params.get("database"):
            return False, DATABASE_NAME_REQUIRED_ERROR

        if not connection_params["is_srv"]:
            # For SRV connections the hostname is a DNS namespace (e.g.
            # cluster0.mongodb.net), not a real host. Actual server addresses
            # are resolved at connection time and validated by
            # _make_safe_server_selector instead.
            # This check allows an early failure for obviously invalid connection strings for non SRV connections.
            valid_host, host_errors = self.is_database_host_valid(connection_params["host"], team_id)
            if not valid_host:
                return False, host_errors

        try:
            collection_names = get_collection_names(config, team_id=team_id)
            if len(collection_names) == 0:
                return False, _MONGO_NO_COLLECTIONS_MESSAGE
        except OperationFailure as e:
            # pymongo's OperationFailure stringifies the full server response — clusterTime,
            # signature hashes, BSON ids — so str(e) must never be surfaced. Map the stable error
            # markers to a clean message; an authorization failure ("not authorized") means the
            # credentials are valid but lack read access, which is distinct from a bad password.
            # Both are user-side credential/permission problems we already surface an actionable
            # message for and classify as non-retryable — never a PostHog bug — so don't report
            # them to error tracking as non-actionable noise.
            message = str(e)
            if "not authorized" in message:
                return False, _MONGO_NOT_AUTHORIZED_MESSAGE
            if any(marker in message for marker in ("AuthenticationFailed", "Authentication failed", "bad auth")):
                return False, _MONGO_AUTHENTICATION_FAILED_MESSAGE
            # Any other OperationFailure on listCollections is unexpected (server bug, unsupported
            # option, ...) — capture it so the signal isn't lost, and surface a generic message
            # rather than mislabelling it as an authentication problem.
            capture_exception(e)
            return False, _MONGO_CONNECT_FAILED_MESSAGE
        except ServerSelectionTimeoutError as e:
            # pymongo dumps a verbose topology description into str(e); surface a concise,
            # actionable message instead. A DNS failure means the host doesn't resolve at all,
            # which is distinct from an allowlist/reachability problem. Server selection only times
            # out on an upstream connectivity problem the user must fix (cluster paused, IP not
            # allowlisted, host unresolved, TLS handshake rejected) — never our bug — and we already
            # return an actionable message for it, so don't report it as error-tracking noise.
            message = str(e)
            if any(marker in message for marker in _DNS_RESOLUTION_FAILURE_MARKERS):
                return False, _MONGO_HOST_UNRESOLVED_MESSAGE
            return False, _MONGO_UNREACHABLE_MESSAGE
        except Exception as e:
            # pymongo raises InvalidURI with the RFC-3986 hint before any network call when the
            # credentials contain unescaped reserved characters. This is a malformed connection
            # string the user must fix — already surfaced with an actionable message — so don't
            # report it to error tracking as a bug. Any other exception is unexpected: capture it
            # and fall back to a generic message so internal exception text never reaches the user.
            if "must be escaped according to RFC 3986" in str(e):
                return False, _MONGO_UNESCAPED_CREDENTIALS_MESSAGE
            capture_exception(e)
            return False, _MONGO_CONNECT_FAILED_MESSAGE

        return True, None

    def source_for_pipeline(self, config: MongoDBSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return mongo_source(
            connection_string=config.connection_string,
            collection_name=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            logger=inputs.logger,
            incremental_field=inputs.incremental_field,
            incremental_field_type=inputs.incremental_field_type,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            team_id=inputs.team_id,
            database_name=config.database_name,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MONGO_DB,
            category=DataWarehouseSourceCategory.DATABASES,
            featured=True,
            keywords=["mongo"],
            label="MongoDB",
            caption="Enter your MongoDB connection string to automatically pull your MongoDB data into the PostHog Data warehouse.",
            releaseStatus=ReleaseStatus.GA,
            iconPath="/static/services/Mongodb.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/mongodb",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="connection_string",
                        label="Connection String",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mongodb://username:password@host:port/database?authSource=admin&tls=true",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="database_name",
                        label="Database name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="my_database",
                        caption=(
                            "Only needed if your connection string doesn't already include the database "
                            "(Atlas `mongodb+srv://...` strings usually don't)."
                        ),
                        secret=False,
                    ),
                ],
            ),
        )
