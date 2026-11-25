import pytest
from unittest.mock import patch

import dns.resolver
import dns.exception
from pymongo.errors import ConfigurationError, InvalidURI, OperationFailure, ServerSelectionTimeoutError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    DATABASE_HOST_NOT_ALLOWED_ERROR,
    DATABASE_HOST_NOT_ALLOWED_GUIDANCE,
    HostNotAllowedError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mongodb import (
    MongoDBSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.mongo import (
    DATABASE_NAME_REQUIRED_ERROR,
    UNSUPPORTED_AUTH_OPTION_ERROR,
    UNSUPPORTED_FILE_OPTION_ERROR,
    UnsupportedAuthOptionError,
    UnsupportedConnectionOptionError,
    is_atlas_srv_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source import (
    _DNS_RESOLUTION_FAILURE_MARKERS,
    _MONGO_AUTHENTICATION_FAILED_MESSAGE,
    _MONGO_CONNECT_FAILED_MESSAGE,
    _MONGO_GSSAPI_UNSUPPORTED_MESSAGE,
    _MONGO_HOST_UNRESOLVED_MESSAGE,
    _MONGO_INVALID_CONNECTION_STRING_MESSAGE,
    _MONGO_NO_COLLECTIONS_MESSAGE,
    _MONGO_NOT_AUTHORIZED_MESSAGE,
    _MONGO_SERVER_TOO_OLD_MESSAGE,
    _MONGO_SRV_RECORD_MISSING_MESSAGE,
    _MONGO_SRV_SCHEME_REQUIRED_MESSAGE,
    _MONGO_UNESCAPED_CREDENTIALS_MESSAGE,
    _MONGO_UNREACHABLE_MESSAGE,
    _MONGO_UNSUPPORTED_AUTH_OPTION_MESSAGE,
    _MONGO_UNSUPPORTED_FILE_OPTION_MESSAGE,
    MongoDBSource,
)

_SRV_NO_DB = "mongodb+srv://user:pass@cluster.abc.mongodb.net/?retryWrites=true&w=majority"
_SRV_WITH_DB = "mongodb+srv://user:pass@cluster.abc.mongodb.net/realdb?retryWrites=true"


class TestMongoValidateCredentialsDatabaseName:
    @pytest.mark.parametrize(
        "connection_string",
        [
            "https://cluster.example.com/db",  # wrong scheme, rejected by our own check
            "mongodb+srv://host:not-a-port/db",  # urlparse rejects the non-numeric port
        ],
    )
    def test_unparseable_connection_string_returns_actionable_error(self, connection_string):
        config = MongoDBSourceConfig.from_dict({"connection_string": connection_string})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == _MONGO_INVALID_CONNECTION_STRING_MESSAGE

    def test_missing_database_everywhere_returns_actionable_error(self):
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_NO_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == DATABASE_NAME_REQUIRED_ERROR

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_database_name_field_satisfies_requirement(self, mock_get_collections):
        mock_get_collections.return_value = ["users"]
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_NO_DB, "database_name": "mydb"})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is True
        assert err is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_no_collections_returns_actionable_error(self, mock_get_collections):
        # Connecting to /admin or /test, or a user lacking read access, surfaces zero collections.
        # That must fail with guidance about the wrong database / missing access, not a terse message.
        mock_get_collections.return_value = []
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_WITH_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == _MONGO_NO_COLLECTIONS_MESSAGE


_HOST_CHECK_ERROR = "Couldn't resolve the host. Check that it's spelled correctly."
_OTHER_HOST_CHECK_ERROR = "Enter a single hostname or IP address for the host."


class TestMongoValidateCredentialsHostCheck:
    @pytest.mark.parametrize(
        "host, host_error, srv_lookup, expected_message, expect_probe",
        [
            ("cluster0.abcde.mongodb.net", _HOST_CHECK_ERROR, None, _MONGO_SRV_SCHEME_REQUIRED_MESSAGE, True),
            ("Cluster0.ABCDE.MongoDB.net", _HOST_CHECK_ERROR, None, _MONGO_SRV_SCHEME_REQUIRED_MESSAGE, True),
            ("cluster0.abcde.mongodb.net", _HOST_CHECK_ERROR, dns.resolver.NXDOMAIN(), _HOST_CHECK_ERROR, True),
            ("cluster0.abcde.mongodb.net", _HOST_CHECK_ERROR, dns.exception.Timeout(), _HOST_CHECK_ERROR, True),
            ("cluster0.abcde.mongodb.net", _OTHER_HOST_CHECK_ERROR, None, _OTHER_HOST_CHECK_ERROR, False),
            ("cluster0.abcde.mongodb.net", None, None, None, False),
            ("db.example.com", _HOST_CHECK_ERROR, None, _HOST_CHECK_ERROR, False),
        ],
    )
    def test_failed_host_check_points_atlas_srv_names_at_the_srv_scheme(
        self, host, host_error, srv_lookup, expected_message, expect_probe
    ):
        # nosemgrep: trailofbits.generic.mongodb-insecure-transport.mongodb-insecure-transport
        config = MongoDBSourceConfig.from_dict({"connection_string": f"mongodb://user:pass@{host}/realdb"})

        with (
            patch.object(MongoDBSource, "is_database_host_valid", return_value=(False, host_error)),
            patch("dns.resolver.resolve", side_effect=srv_lookup) as mock_resolve,
        ):
            ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == expected_message
        assert mock_resolve.called is expect_probe


class TestIsAtlasSrvName:
    @pytest.mark.parametrize(
        "host",
        [
            "evil.example\\.mongodb.net",
            "evil.example\\046.mongodb.net",
            "cluster0.abcde.mongodb.net.",
            "cluster0.abcde.mongodb.net.example.com",
            "cluster0.abcde.notmongodb.net",
            "mongodb.net",
            "cluster0 .abcde.mongodb.net",
            "cluster0.abcde.mongodb.net:27017",
        ],
    )
    def test_names_outside_atlas_never_reach_the_resolver(self, host):
        with patch("dns.resolver.resolve") as mock_resolve:
            assert is_atlas_srv_name(host) is False

        mock_resolve.assert_not_called()


class TestMongoValidateCredentialsServerSelection:
    @pytest.mark.parametrize("marker", _DNS_RESOLUTION_FAILURE_MARKERS)
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_dns_resolution_failure_returns_unresolved_message(self, mock_get_collections, marker):
        # The verbose topology-description message pymongo raises when the host doesn't resolve.
        mock_get_collections.side_effect = ServerSelectionTimeoutError(
            f"cluster0.qwi73.mongodb.net:27017: [Errno -5] {marker} "
            "(configured timeouts: socketTimeoutMS: 20000.0ms), Topology Description: <TopologyDescription ...>"
        )
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_WITH_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == _MONGO_HOST_UNRESOLVED_MESSAGE
        assert "Topology Description" not in (err or "")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_private_srv_members_return_host_guidance(self, mock_get_collections):
        # An SRV URI skips the up-front host check, so the connect form only learns the members are
        # private when the server selector refuses them. That must read as a host problem rather
        # than the generic connect failure, which also reports to error tracking.
        mock_get_collections.side_effect = HostNotAllowedError(f"{DATABASE_HOST_NOT_ALLOWED_ERROR}: internal IP")
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_WITH_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == DATABASE_HOST_NOT_ALLOWED_GUIDANCE

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_unreachable_cluster_returns_allowlist_message(self, mock_get_collections):
        mock_get_collections.side_effect = ServerSelectionTimeoutError(
            "No servers found yet, Topology Description: ..."
        )
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_WITH_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == _MONGO_UNREACHABLE_MESSAGE


class TestMongoValidateCredentialsOperationFailure:
    # All values here are synthetic — pymongo appends the full server response (clusterTime,
    # signature, BSON ids) to str(e), and that raw text must never reach the user. Each row
    # exercises a distinct branch: two inside `except OperationFailure`, two inside `except Exception`.
    @pytest.mark.parametrize(
        "exc, expected_message, forbidden",
        [
            (
                OperationFailure(
                    "not authorized on demo_db to execute command { listCollections: 1 }",
                    13,
                    {
                        "ok": 0.0,
                        "errmsg": "not authorized on demo_db to execute command { listCollections: 1 }",
                        "code": 13,
                        "codeName": "Unauthorized",
                        "$clusterTime": {"clusterTime": "Timestamp(1, 1)", "signature": {"keyId": 1234567890}},
                    },
                ),
                _MONGO_NOT_AUTHORIZED_MESSAGE,
                ("full error", "signature", "clusterTime", "keyId", "demo_db"),
            ),
            (
                OperationFailure(
                    "Authentication failed.", 18, {"ok": 0.0, "errmsg": "Authentication failed.", "code": 18}
                ),
                _MONGO_AUTHENTICATION_FAILED_MESSAGE,
                ("full error",),
            ),
            (
                InvalidURI("Username and password must be escaped according to RFC 3986, use urllib.parse.quote_plus"),
                _MONGO_UNESCAPED_CREDENTIALS_MESSAGE,
                (),
            ),
            (
                Exception("some-internal-driver-detail-xyz"),
                _MONGO_CONNECT_FAILED_MESSAGE,
                ("xyz",),
            ),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_returns_clean_message_without_internals(self, mock_get_collections, exc, expected_message, forbidden):
        mock_get_collections.side_effect = exc
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_WITH_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == expected_message
        for leaked in forbidden:
            assert leaked not in (err or "")


class TestMongoValidateCredentialsErrorTrackingNoise:
    # Errors we already surface an actionable message for are user/upstream problems, not our bug,
    # so they must not be reported to error tracking; genuinely unexpected errors still must be.
    # The SSL-handshake host/port here are redacted — matching a real customer value would leak it.
    @pytest.mark.parametrize(
        "exc, expected_message, should_capture",
        [
            (
                InvalidURI("Username and password must be escaped according to RFC 3986, use urllib.parse.quote_plus"),
                _MONGO_UNESCAPED_CREDENTIALS_MESSAGE,
                False,
            ),
            (
                ServerSelectionTimeoutError(
                    "SSL handshake failed: <redacted-host>:27017: [SSL: TLSV1_ALERT_INTERNAL_ERROR] "
                    "tlsv1 alert internal error, Topology Description: <TopologyDescription ...>"
                ),
                _MONGO_UNREACHABLE_MESSAGE,
                False,
            ),
            (
                # dnspython's NXDOMAIN, wrapped by pymongo as ConfigurationError, when a
                # mongodb+srv:// URI's SRV DNS record doesn't exist at all.
                ConfigurationError("The DNS query name does not exist: _mongodb._tcp.cluster.abc.mongodb.net."),
                _MONGO_HOST_UNRESOLVED_MESSAGE,
                False,
            ),
            (
                # dnspython's NoAnswer, wrapped by pymongo as ConfigurationError, when the host
                # resolves but publishes no `_mongodb._tcp` SRV record at all.
                ConfigurationError(
                    "The DNS response does not contain an answer to the question: "
                    "_mongodb._tcp.cluster.abc.mongodb.net. IN SRV"
                ),
                _MONGO_SRV_RECORD_MISSING_MESSAGE,
                False,
            ),
            (
                # pymongo's server-selection wording for a server below the driver's minimum wire version.
                ConfigurationError(
                    "Server at cluster.abc.mongodb.net:27017 reports wire version 7, but this version of "
                    "PyMongo requires at least 8 (MongoDB 4.2)."
                ),
                _MONGO_SERVER_TOO_OLD_MESSAGE,
                False,
            ),
            (
                # pymongo's fixed message when authMechanism=GSSAPI is set but the optional
                # pykerberos/winkerberos package isn't installed.
                ConfigurationError('The "kerberos" module must be installed to use GSSAPI authentication.'),
                _MONGO_GSSAPI_UNSUPPORTED_MESSAGE,
                False,
            ),
            (
                # An unrecognized ConfigurationError still falls back to capturing, same as any
                # other unexpected exception.
                ConfigurationError("some-unrecognized-configuration-problem"),
                _MONGO_CONNECT_FAILED_MESSAGE,
                True,
            ),
            (Exception("some-internal-driver-detail"), _MONGO_CONNECT_FAILED_MESSAGE, True),
            (
                UnsupportedConnectionOptionError(UNSUPPORTED_FILE_OPTION_ERROR),
                _MONGO_UNSUPPORTED_FILE_OPTION_MESSAGE,
                False,
            ),
            (
                UnsupportedAuthOptionError(UNSUPPORTED_AUTH_OPTION_ERROR),
                _MONGO_UNSUPPORTED_AUTH_OPTION_MESSAGE,
                False,
            ),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.capture_exception")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_capture_only_for_unexpected_errors(
        self, mock_get_collections, mock_capture, exc, expected_message, should_capture
    ):
        mock_get_collections.side_effect = exc
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_WITH_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == expected_message
        assert mock_capture.called is should_capture

    # A recognized OperationFailure on listCollections is a user-side credential/permission problem
    # — a missing read role ("not authorized") or bad credentials — that we already surface an
    # actionable message for and classify as non-retryable, so it must not be captured as noise. An
    # unrecognized OperationFailure is unexpected and must still be captured so the signal isn't lost.
    @pytest.mark.parametrize(
        "exc, expected_message, should_capture",
        [
            (
                OperationFailure(
                    "not authorized on demo_db to execute command { listCollections: 1 }",
                    13,
                    {"ok": 0.0, "errmsg": "not authorized on demo_db", "code": 13, "codeName": "Unauthorized"},
                ),
                _MONGO_NOT_AUTHORIZED_MESSAGE,
                False,
            ),
            (
                OperationFailure(
                    "Authentication failed.", 18, {"ok": 0.0, "errmsg": "Authentication failed.", "code": 18}
                ),
                _MONGO_AUTHENTICATION_FAILED_MESSAGE,
                False,
            ),
            (
                OperationFailure(
                    "bad auth : authentication failed",
                    8000,
                    {"ok": 0.0, "errmsg": "bad auth : authentication failed", "code": 8000, "codeName": "AtlasError"},
                ),
                _MONGO_AUTHENTICATION_FAILED_MESSAGE,
                False,
            ),
            (
                OperationFailure(
                    "listCollections: unrecognized field 'authorizedCollections'",
                    40415,
                    {"ok": 0.0, "errmsg": "unrecognized field", "code": 40415, "codeName": "Location40415"},
                ),
                _MONGO_CONNECT_FAILED_MESSAGE,
                True,
            ),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.capture_exception")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_operation_failure_capture_behavior(
        self, mock_get_collections, mock_capture, exc, expected_message, should_capture
    ):
        mock_get_collections.side_effect = exc
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_WITH_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == expected_message
        assert mock_capture.called is should_capture
