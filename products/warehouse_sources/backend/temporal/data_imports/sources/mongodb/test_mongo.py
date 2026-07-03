import uuid
import base64
import datetime

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from bson import Binary, DatetimeMS, ObjectId
from bson.binary import UUID_SUBTYPE
from parameterized import parameterized
from pymongo.errors import ServerSelectionTimeoutError
from pymongo.server_description import ServerDescription

from products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.mongo import (
    _build_query,
    _get_rows_to_sync,
    _list_importable_collection_names,
    _make_safe_server_selector,
    _process_doc_with_field_logging,
    _process_nested_value,
    get_leading_index_keys,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


class TestSafeServerSelector(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_filters_out_servers_with_internal_ips(self):
        selector = _make_safe_server_selector(team_id=999)
        servers = [
            ServerDescription(("10.0.0.1", 27017)),
            ServerDescription(("8.8.8.8", 27017)),
        ]

        result = selector(servers)

        assert len(result) == 1
        assert result[0].address == ("8.8.8.8", 27017)

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_returns_empty_when_all_servers_internal(self):
        selector = _make_safe_server_selector(team_id=999)
        servers = [
            ServerDescription(("10.0.0.1", 27017)),
            ServerDescription(("192.168.1.1", 27017)),
        ]

        result = selector(servers)

        assert result == []

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_all_public_servers(self):
        selector = _make_safe_server_selector(team_id=999)
        servers = [
            ServerDescription(("8.8.8.8", 27017)),
            ServerDescription(("1.1.1.1", 27017)),
        ]

        result = selector(servers)

        assert len(result) == 2

    @parameterized.expand(
        [
            ("loopback", "127.0.0.1"),
            ("link_local_imds", "169.254.169.254"),
            ("private_172", "172.16.0.1"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_blocks_various_internal_addresses(self, _name: str, host: str):
        selector = _make_safe_server_selector(team_id=999)
        servers = [ServerDescription((host, 27017))]

        result = selector(servers)

        assert result == []

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_whitelisted_team_allows_internal_ips(self):
        selector = _make_safe_server_selector(team_id=2)
        servers = [ServerDescription(("10.0.0.1", 27017))]

        result = selector(servers)

        assert len(result) == 1

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.is_cloud", return_value=False
    )
    def test_self_hosted_allows_internal_ips(self, _mock_is_cloud):
        selector = _make_safe_server_selector(team_id=999)
        servers = [ServerDescription(("10.0.0.1", 27017))]

        result = selector(servers)

        assert len(result) == 1


class TestProcessNestedValue(SimpleTestCase):
    CANONICAL_UUID_STR = "00000015-af12-f829-04fe-1f5e8f1a5230"
    CANONICAL_UUID = uuid.UUID(CANONICAL_UUID_STR)
    YEAR_ZERO_MS = -62167219200000  # 0000-01-01T00:00:00Z
    FAR_FUTURE_MS = 253_402_300_800_000 * 10  # year > 9999

    def test_objectid_is_stringified(self):
        oid = ObjectId()
        assert _process_nested_value(oid) == str(oid)

    def test_uuid_is_stringified(self):
        assert _process_nested_value(self.CANONICAL_UUID) == self.CANONICAL_UUID_STR

    def test_binary_legacy_subtype_3_decodes_as_uuid(self):
        # Subtype 4 (standard UUID) is pre-decoded to uuid.UUID by PyMongo's
        # codec and never reaches _convert_binary; only legacy subtype 3 exercises
        # the Binary → UUID branch here.
        binary = Binary(self.CANONICAL_UUID.bytes, 3)
        assert _process_nested_value(binary) == self.CANONICAL_UUID_STR

    @parameterized.expand(
        [
            ("generic_subtype", b"\x00\x01\x02\x03payload", 0),
            # Subtype 4 Binary should not reach _convert_binary in production
            # (codec decodes to uuid.UUID first), but if it does, the wrong-length
            # guard falls back to base64 rather than crashing.
            ("subtype_4_wrong_length", b"\x00\x01\x02", UUID_SUBTYPE),
            ("subtype_4_full_length", b"\x00" * 16, UUID_SUBTYPE),
        ]
    )
    def test_non_decodable_binary_falls_back_to_base64(self, _name: str, raw: bytes, subtype: int):
        binary = Binary(raw, subtype)
        assert _process_nested_value(binary) == base64.b64encode(raw).decode("ascii")

    def test_nested_dict_with_uuid(self):
        value = {
            "user": {
                "_id": self.CANONICAL_UUID,
                "name": "Alice",
            },
        }

        result = _process_nested_value(value)

        assert result == {
            "user": {
                "_id": self.CANONICAL_UUID_STR,
                "name": "Alice",
            }
        }

    def test_list_with_mixed_bson_types(self):
        oid = ObjectId()
        value = [oid, self.CANONICAL_UUID, "plain"]

        assert _process_nested_value(value) == [str(oid), self.CANONICAL_UUID_STR, "plain"]

    @parameterized.expand(
        [
            ("int", 42),
            ("string", "hello"),
            ("none", None),
            ("bool_true", True),
            ("bool_false", False),
            ("float", 3.14),
        ]
    )
    def test_plain_values_pass_through(self, _name: str, value):
        assert _process_nested_value(value) == value

    def test_never_produces_bytes_repr(self):
        # Regression: UUID must never leak as b'\x...' repr downstream.
        result = _process_nested_value(self.CANONICAL_UUID)

        assert isinstance(result, str)
        assert not result.startswith("b'")
        assert "\\x" not in result

    def test_datetime_in_range_passes_through(self):
        # Native datetime (in-range under DATETIME_AUTO) is returned unchanged.
        dt = datetime.datetime(2024, 6, 1, 12, 30, 0)
        assert _process_nested_value(dt) is dt

    def test_datetime_ms_in_range_converted_to_datetime(self):
        # DatetimeMS within the datetime representable range: as_datetime succeeds.
        # Under DATETIME_AUTO this only arises for out-of-range values, but the
        # helper must still handle in-range DatetimeMS gracefully if it appears.
        ms = 1_700_000_000_000  # 2023-11-14T22:13:20Z
        result = _process_nested_value(DatetimeMS(ms))
        assert isinstance(result, datetime.datetime)

    @parameterized.expand(
        [
            ("year_zero", YEAR_ZERO_MS),
            ("far_future", FAR_FUTURE_MS),
        ]
    )
    def test_datetime_ms_out_of_range_becomes_none(self, _name: str, ms: int):
        assert _process_nested_value(DatetimeMS(ms)) is None

    def test_nested_dict_with_out_of_range_datetime(self):
        value = {
            "user": {
                "dateOfBirth": DatetimeMS(self.YEAR_ZERO_MS),
                "createdAt": datetime.datetime(2024, 1, 1),
            },
        }

        result = _process_nested_value(value)

        assert result == {
            "user": {
                "dateOfBirth": None,
                "createdAt": datetime.datetime(2024, 1, 1),
            }
        }


class TestProcessDocWithFieldLogging(SimpleTestCase):
    def _logger(self) -> MagicMock:
        return MagicMock()

    def test_happy_path_passes_through_all_fields(self):
        logger = self._logger()
        doc = {"_id": "abc", "name": "Alice", "age": 42}

        result = _process_doc_with_field_logging(doc, "users", logger)

        assert result == {"_id": "abc", "name": "Alice", "age": 42}
        logger.exception.assert_not_called()

    def test_failed_field_reraises_and_logs_field_name(self):
        logger = self._logger()

        class BadDict(dict):
            def items(self):
                raise RuntimeError("synthetic items() failure")

        doc = {"_id": "abc", "good": "value", "bad_field": BadDict()}

        # Must re-raise so the sync fails fast rather than silently nulling data.
        with self.assertRaises(RuntimeError):
            _process_doc_with_field_logging(doc, "users", logger)

        logger.exception.assert_called_once()
        log_msg = logger.exception.call_args[0][0]
        assert "bad_field" in log_msg
        assert "users" in log_msg
        assert "_id=abc" in log_msg

    def test_failure_points_at_first_failing_field(self):
        logger = self._logger()

        class BadList(list):
            def __iter__(self):
                raise RuntimeError("synthetic iter failure")

        # `broken` comes before `last` — must raise at `broken` without processing `last`.
        doc = {
            "_id": "abc",
            "first": "ok",
            "broken": BadList(),
            "last": "also_ok",
        }

        with self.assertRaises(RuntimeError):
            _process_doc_with_field_logging(doc, "orders", logger)

        log_msg = logger.exception.call_args[0][0]
        assert "'broken'" in log_msg

    def test_log_includes_unavailable_id_when_id_lookup_fails(self):
        logger = self._logger()

        class DictNoId(dict):
            def get(self, key, default=None):
                if key == "_id":
                    raise RuntimeError("cannot access _id")
                return super().get(key, default)

        class BadList(list):
            def __iter__(self):
                raise RuntimeError("synthetic iter failure")

        doc = DictNoId({"broken": BadList()})

        with self.assertRaises(RuntimeError):
            _process_doc_with_field_logging(doc, "things", logger)

        log_msg = logger.exception.call_args[0][0]
        assert "_id=<unavailable>" in log_msg


class TestGetLeadingIndexKeys(SimpleTestCase):
    """The MongoDB warning hinges on whether the user's chosen incremental
    field is the *leading* key of any index — non-leading positions in compound
    indexes don't speed up `WHERE field >= last_max` queries.
    """

    @staticmethod
    def _collection_with_indexes(indexes):
        coll = MagicMock()
        coll.list_indexes.return_value = iter(indexes)
        return coll

    def test_collects_leading_keys_only(self):
        coll = self._collection_with_indexes(
            [
                {"key": {"_id": 1}},
                {"key": {"updated_at": -1}},
                # `user_id` is the leading key here; `created_at` is not
                {"key": {"user_id": 1, "created_at": 1}},
            ]
        )
        assert get_leading_index_keys(coll) == {"_id", "updated_at", "user_id"}

    def test_returns_none_on_failure(self):
        coll = MagicMock()
        coll.list_indexes.side_effect = RuntimeError("network down")
        assert get_leading_index_keys(coll) is None

    def test_returns_empty_set_for_collection_with_no_indexes(self):
        coll = self._collection_with_indexes([])
        assert get_leading_index_keys(coll) == set()


class TestBuildQuery(SimpleTestCase):
    """`_id` is offered as an ObjectID incremental cursor, but MongoDB `_id` values aren't
    always ObjectIds — a non-ObjectId cursor must not crash query construction."""

    _OID_HEX = "507f1f77bcf86cd799439011"
    _UUID = "fffdb62e-4704-4671-984c-ffcff3a8dd52"

    @parameterized.expand(
        [
            # A valid 24-char hex cursor stays an ObjectId so native ordered comparison is preserved.
            ("objectid_cursor_is_wrapped", _OID_HEX, ObjectId(_OID_HEX)),
            # Regression: a UUID-string `_id` previously raised bson.errors.InvalidId here,
            # permanently breaking every incremental sync for collections that key on UUIDs.
            ("uuid_cursor_compares_as_string", _UUID, _UUID),
        ]
    )
    def test_cursor_coercion(self, _name: str, cursor: str, expected_gt):
        query = _build_query(True, "_id", IncrementalFieldType.ObjectID, cursor)
        assert query == {"_id": {"$gt": expected_gt, "$exists": True}}


class TestMongoDBNonRetryableErrors(SimpleTestCase):
    """The non-retryable match is case-sensitive substring matching, so the patterns
    must match the exact casing pymongo produces."""

    def setUp(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.source import MongoDBSource

        self.non_retryable = MongoDBSource().get_non_retryable_errors()

    @parameterized.expand(
        [
            # Real pymongo OperationFailure string for bad credentials (code 18).
            (
                "operation_failure",
                "Authentication failed., full error: {'ok': 0.0, 'errmsg': 'Authentication failed.', "
                "'code': 18, 'codeName': 'AuthenticationFailed'}",
            ),
            # Real pymongo OperationFailure string for bad credentials on MongoDB Atlas (code 8000).
            (
                "atlas_bad_auth",
                "bad auth : authentication failed, full error: {'ok': 0, 'errmsg': 'bad auth : "
                "authentication failed', 'code': 8000, 'codeName': 'AtlasError'}",
            ),
            ("dns_failure", "The DNS query name does not exist: example.mongodb.net."),
            ("ssl_failure", "SSL handshake failed: certificate verify failed"),
            # pymongo InvalidURI raised before any network call when credentials in the connection
            # string contain unescaped reserved characters — a malformed string the user must fix.
            (
                "unescaped_credentials",
                "Username and password must be escaped according to RFC 3986, use urllib.parse.quote_plus",
            ),
            # Same unescaped-credential mistake surfacing via the "Port contains non-digit characters"
            # variant, which carries the identical RFC-3986 hint.
            (
                "unescaped_credentials_port_variant",
                "Port contains non-digit characters. Hint: username and password must be escaped "
                "according to RFC 3986, use urllib.parse.quote_plus",
            ),
            # ServerSelectionTimeoutError variants — cluster unreachable for the whole selection
            # timeout. All carry the "Topology Description:" suffix regardless of the per-reason text.
            ("no_servers", "No servers found yet, Timeout: 5.0s, Topology Description: ..."),
            (
                "no_replica_set_members",
                "No replica set members found yet, Timeout: 10.0s, Topology Description: "
                "<TopologyDescription topology_type: ReplicaSetNoPrimary>",
            ),
            # Host resolves but every connection attempt is closed for the whole window — the driver
            # never identifies the server (topology_type: Unknown) and wraps the per-server
            # AutoReconnect. Persistent connectivity/config problem, not a momentary blip.
            (
                "connection_closed_selection_timeout",
                "cluster0.example.mongodb.net:27017: connection closed (configured timeouts: "
                "socketTimeoutMS: 20000.0ms, connectTimeoutMS: 20000.0ms), Timeout: 10.0s, "
                "Topology Description: <TopologyDescription id: abc, topology_type: Unknown, "
                "servers: [<ServerDescription ('cluster0.example.mongodb.net', 27017) "
                "server_type: Unknown, rtt: None, error=AutoReconnect('cluster0.example.mongodb.net:"
                "27017: connection closed (configured timeouts: socketTimeoutMS: 20000.0ms, "
                "connectTimeoutMS: 20000.0ms)')>]>",
            ),
            # Atlas SQL / Data Federation endpoint (*.query.mongodb.net) — unusable by the standard
            # driver, so the topology stays Unknown and selection times out. Despite the "connection
            # closed" text, the host suffix marks it as a wrong-endpoint config error, not a blip.
            (
                "atlas_sql_endpoint",
                "atlas-sql-681905984ce3f87167df11fa-wf3cgp.a.query.mongodb.net:27017: connection closed "
                "(configured timeouts: socketTimeoutMS: 20000.0ms, connectTimeoutMS: 20000.0ms), Timeout: "
                "10.0s, Topology Description: <TopologyDescription id: 6a304febea674ebc4c8c051e, "
                "topology_type: Unknown, servers: [<ServerDescription "
                "('atlas-sql-681905984ce3f87167df11fa-wf3cgp.a.query.mongodb.net', 27017) "
                "server_type: Unknown, rtt: None, error=AutoReconnect('...connection closed...')>]>",
            ),
        ]
    )
    def test_known_errors_are_non_retryable(self, _name, error_msg):
        assert any(pattern in error_msg for pattern in self.non_retryable), (
            f"MongoDB error {error_msg!r} did not match any non-retryable pattern"
        )

    @parameterized.expand(
        [
            ("connection_reset", "connection closed"),
            ("network_timeout", "NetworkTimeout: timed out reading from socket"),
            # A mid-sync AutoReconnect carries the "(configured timeouts: ...)" suffix but no
            # topology description — it's a momentary drop the driver can recover from, so it must
            # not be caught by the "Topology Description:" server-selection matcher.
            (
                "mid_sync_auto_reconnect",
                "cluster0.example.mongodb.net:27017: connection closed (configured timeouts: "
                "socketTimeoutMS: 20000.0ms, connectTimeoutMS: 20000.0ms)",
            ),
        ]
    )
    def test_transient_errors_are_retryable(self, _name, error_msg):
        assert not any(pattern in error_msg for pattern in self.non_retryable), (
            f"MongoDB error {error_msg!r} should remain retryable"
        )

    @parameterized.expand(
        [
            ("code_name", "AuthenticationFailed", "password"),
            ("message", "Authentication failed", "password"),
            ("atlas_bad_auth", "bad auth", "password"),
            ("unreachable_topology", "Topology Description:", "allowlist"),
            ("atlas_sql_endpoint", "query.mongodb.net", "connection string"),
            ("unescaped_credentials", "must be escaped according to RFC 3986", "connection string"),
        ]
    )
    def test_pattern_has_friendly_message(self, _name, pattern, expected_substring):
        message = self.non_retryable[pattern]
        assert message is not None
        assert expected_substring in message.lower()


class TestGetRowsToSync(SimpleTestCase):
    """rows_to_sync is a best-effort progress estimate; a failed count must degrade to
    0 without failing the sync, and expected pymongo errors must not be reported to
    error tracking (they are transient/operational and classified by the real data read)."""

    def test_returns_count_on_success(self):
        coll = MagicMock()
        coll.count_documents.return_value = 42
        assert _get_rows_to_sync(coll, {}, MagicMock()) == 42

    def test_pymongo_error_returns_zero_without_capture(self):
        coll = MagicMock()
        coll.count_documents.side_effect = ServerSelectionTimeoutError(
            "atlas-sql.query.mongodb.net:27017: connection closed, Timeout: 10.0s"
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.mongo.capture_exception"
        ) as capture:
            assert _get_rows_to_sync(coll, {}, MagicMock()) == 0
            capture.assert_not_called()

    def test_unexpected_error_returns_zero_and_captures(self):
        coll = MagicMock()
        coll.count_documents.side_effect = ValueError("unexpected bug")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mongodb.mongo.capture_exception"
        ) as capture:
            assert _get_rows_to_sync(coll, {}, MagicMock()) == 0
            capture.assert_called_once()


class TestListImportableCollectionNames(SimpleTestCase):
    def test_excludes_reserved_system_collections(self):
        db = MagicMock()
        db.list_collection_names.return_value = ["users", "system.keys", "orders", "system.views"]

        assert _list_importable_collection_names(db) == ["users", "orders"]

    def test_keeps_collections_that_merely_contain_system(self):
        db = MagicMock()
        db.list_collection_names.return_value = ["system_events", "billing.system", "systematic"]

        assert _list_importable_collection_names(db) == ["system_events", "billing.system", "systematic"]
