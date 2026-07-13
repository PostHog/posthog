import pytest
from unittest.mock import patch

from pymongo.errors import InvalidURI, OperationFailure, ServerSelectionTimeoutError

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MongoDBSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.mongo import (
    DATABASE_NAME_REQUIRED_ERROR,
    _parse_connection_string,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source import (
    _DNS_RESOLUTION_FAILURE_MARKERS,
    _MONGO_AUTHENTICATION_FAILED_MESSAGE,
    _MONGO_CONNECT_FAILED_MESSAGE,
    _MONGO_HOST_UNRESOLVED_MESSAGE,
    _MONGO_NO_COLLECTIONS_MESSAGE,
    _MONGO_NOT_AUTHORIZED_MESSAGE,
    _MONGO_UNESCAPED_CREDENTIALS_MESSAGE,
    _MONGO_UNREACHABLE_MESSAGE,
    MongoDBSource,
)

_SRV_NO_DB = "mongodb+srv://user:pass@cluster.abc.mongodb.net/?retryWrites=true&w=majority"
_SRV_WITH_DB = "mongodb+srv://user:pass@cluster.abc.mongodb.net/realdb?retryWrites=true"


class TestParseConnectionStringDatabaseOverride:
    def test_uses_override_when_connection_string_omits_database(self):
        # Atlas SRV strings routinely have no `/<db>` path — the separate field fills it.
        params = _parse_connection_string(_SRV_NO_DB, database_override="mydb")
        assert params["database"] == "mydb"

    def test_connection_string_database_wins_over_override(self):
        params = _parse_connection_string(_SRV_WITH_DB, database_override="ignored")
        assert params["database"] == "realdb"

    @pytest.mark.parametrize("override", [None, "", "   "])
    def test_no_usable_override_leaves_database_empty(self, override):
        # The trailing `/` makes the parsed path empty, so `database` is falsy
        # (the downstream "is db missing" checks treat "" and None the same).
        params = _parse_connection_string(_SRV_NO_DB, database_override=override)
        assert not params["database"]


class TestMongoValidateCredentialsDatabaseName:
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
            (Exception("some-internal-driver-detail"), _MONGO_CONNECT_FAILED_MESSAGE, True),
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
