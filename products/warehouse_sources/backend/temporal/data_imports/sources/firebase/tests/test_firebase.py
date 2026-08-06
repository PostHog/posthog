import json
from typing import Any, Optional

import pytest
from unittest import mock

import jwt
import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.firebase import (
    AccessTokenProvider,
    FirebaseAuthError,
    FirebaseConfigError,
    FirebaseResumeConfig,
    build_jwt_assertion,
    decode_firestore_value,
    firebase_source,
    flatten_auth_user,
    flatten_firestore_document,
    flatten_realtime_database_child,
    get_rows,
    get_tables,
    iter_auth_users,
    iter_firestore_documents,
    iter_realtime_database,
    list_collection_ids,
    mint_access_token,
    validate_credentials,
    validate_realtime_database_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.settings import (
    AUTH_USERS_TABLE,
    FIRESTORE_CREATE_TIME_COLUMN,
    FIRESTORE_ID_COLUMN,
    FIRESTORE_PATH_COLUMN,
    FIRESTORE_UPDATE_TIME_COLUMN,
    GOOGLE_TOKEN_URI,
    OAUTH_SCOPES,
    REALTIME_DATABASE_KEY_COLUMN,
    REALTIME_DATABASE_PAGE_SIZE,
    REALTIME_DATABASE_PATH_COLUMN,
    REALTIME_DATABASE_VALUE_COLUMN,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.tests.conftest import (
    PUBLIC_KEY_PEM,
    TOKEN_PAYLOAD,
    FakeResponse,
    FakeResumeManager,
    FakeSession,
    credentials,
)

_SESSION_FACTORY = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.firebase.firebase.make_tracked_session"
)

DOCUMENTS_ROOT = "https://firestore.googleapis.com/v1/projects/demo-project/databases/(default)/documents"


def token_provider(session: FakeSession) -> AccessTokenProvider:
    return AccessTokenProvider(session.as_session(), credentials())


def firestore_document(document_id: str, fields: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {
        "name": f"projects/demo-project/databases/(default)/documents/rooms/{document_id}",
        "fields": fields if fields is not None else {"title": {"stringValue": document_id}},
        "createTime": "2024-01-02T03:04:05.000000Z",
        "updateTime": "2024-05-06T07:08:09.000000Z",
    }


class TestFirestoreValueDecoding:
    @pytest.mark.parametrize(
        "wrapper,expected",
        [
            ({"stringValue": "hello"}, "hello"),
            ({"integerValue": "42"}, 42),
            ({"integerValue": "not-a-number"}, None),
            ({"doubleValue": 1.5}, 1.5),
            ({"booleanValue": False}, False),
            ({"nullValue": "NULL_VALUE"}, None),
            ({"timestampValue": "2024-01-01T00:00:00Z"}, "2024-01-01T00:00:00Z"),
            ({"bytesValue": "aGk="}, "aGk="),
            (
                {"referenceValue": "projects/p/databases/(default)/documents/rooms/a"},
                "projects/p/databases/(default)/documents/rooms/a",
            ),
            ({"geoPointValue": {"latitude": 1.0, "longitude": 2.0}}, {"latitude": 1.0, "longitude": 2.0}),
            ({"arrayValue": {"values": [{"stringValue": "a"}, {"integerValue": "2"}]}}, ["a", 2]),
            ({"arrayValue": {}}, []),
            ({"mapValue": {"fields": {"inner": {"stringValue": "x"}}}}, {"inner": "x"}),
            ({"pipelineValue": {}}, None),
            ("not-a-wrapper", None),
        ],
    )
    def test_decodes_every_stored_value_type(self, wrapper: Any, expected: Any) -> None:
        assert decode_firestore_value(wrapper) == expected

    def test_nested_containers_are_json_encoded_so_the_column_type_is_stable(self) -> None:
        row = flatten_firestore_document(
            firestore_document(
                "abc",
                {
                    "title": {"stringValue": "Lobby"},
                    "members": {"arrayValue": {"values": [{"stringValue": "a"}]}},
                    "meta": {"mapValue": {"fields": {"pinned": {"booleanValue": True}}}},
                },
            )
        )

        assert row["title"] == "Lobby"
        assert json.loads(row["members"]) == ["a"]
        assert json.loads(row["meta"]) == {"pinned": True}

    def test_metadata_columns_describe_the_document(self) -> None:
        row = flatten_firestore_document(firestore_document("abc"))

        assert row[FIRESTORE_ID_COLUMN] == "abc"
        assert row[FIRESTORE_PATH_COLUMN] == "rooms/abc"
        assert row[FIRESTORE_CREATE_TIME_COLUMN] == "2024-01-02T03:04:05.000000Z"
        assert row[FIRESTORE_UPDATE_TIME_COLUMN] == "2024-05-06T07:08:09.000000Z"

    def test_document_with_no_fields_still_produces_metadata(self) -> None:
        row = flatten_firestore_document({"name": "", "createTime": None, "updateTime": None})

        assert row[FIRESTORE_ID_COLUMN] == ""
        assert row[FIRESTORE_PATH_COLUMN] == ""


class TestRowFlattening:
    def test_auth_user_drops_password_material(self) -> None:
        row = flatten_auth_user(
            {
                "localId": "u1",
                "email": "a@example.com",
                "passwordHash": "hash",
                "salt": "salt",
                "rawPassword": "hunter2",
                "providerUserInfo": [{"providerId": "google.com"}],
            }
        )

        assert set(row) == {"localId", "email", "providerUserInfo"}
        assert json.loads(row["providerUserInfo"]) == [{"providerId": "google.com"}]

    @pytest.mark.parametrize(
        "value,expected_columns",
        [
            ({"name": "Lobby", "size": 3}, {"name": "Lobby", "size": 3}),
            ({"nested": {"a": 1}}, {"nested": '{"a": 1}'}),
            ("scalar", {REALTIME_DATABASE_VALUE_COLUMN: "scalar"}),
            (7, {REALTIME_DATABASE_VALUE_COLUMN: 7}),
        ],
    )
    def test_realtime_database_child_shapes(self, value: Any, expected_columns: dict[str, Any]) -> None:
        row = flatten_realtime_database_child("rooms", "k1", value)

        assert row[REALTIME_DATABASE_KEY_COLUMN] == "k1"
        assert row[REALTIME_DATABASE_PATH_COLUMN] == "rooms/k1"
        for column, expected in expected_columns.items():
            assert row[column] == expected


class TestAccessTokens:
    def test_assertion_is_signed_for_googles_token_endpoint(self) -> None:
        assertion = build_jwt_assertion(credentials())

        claims = jwt.decode(
            assertion, PUBLIC_KEY_PEM, algorithms=["RS256"], audience="https://oauth2.googleapis.com/token"
        )
        assert claims["iss"] == "importer@demo-project.iam.gserviceaccount.com"
        assert claims["scope"] == OAUTH_SCOPES
        assert jwt.get_unverified_header(assertion)["kid"] == "key-id"

    def test_token_uri_from_the_key_file_cannot_retarget_the_exchange(self) -> None:
        hostile = credentials(token_uri="http://169.254.169.254/latest/meta-data/")
        session = FakeSession(post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)])

        mint_access_token(session.as_session(), hostile)

        assert session.posts[0][0] == GOOGLE_TOKEN_URI
        claims = jwt.decode(
            session.posts[0][1]["data"]["assertion"],
            PUBLIC_KEY_PEM,
            algorithms=["RS256"],
            audience=GOOGLE_TOKEN_URI,
        )
        assert claims["aud"] == GOOGLE_TOKEN_URI

    def test_unreadable_private_key_is_reported_as_an_auth_error(self) -> None:
        with pytest.raises(FirebaseAuthError, match="could not be read"):
            build_jwt_assertion(credentials(private_key="not-a-key"))

    def test_mint_returns_the_token_and_its_lifetime(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)])

        assert mint_access_token(session.as_session(), credentials()) == ("tok-1", 3600)

    @pytest.mark.parametrize(
        "response,message",
        [
            (FakeResponse(status_code=400, payload={"error": "invalid_grant"}), "invalid_grant"),
            (FakeResponse(status_code=403, payload={"error": {"status": "PERMISSION_DENIED"}}), "PERMISSION_DENIED"),
            (FakeResponse(payload={"token_type": "Bearer"}), "did not contain an access token"),
        ],
    )
    def test_token_failures_raise_with_googles_reason(self, response: FakeResponse, message: str) -> None:
        session = FakeSession(post_responses=[response])

        with pytest.raises(FirebaseAuthError, match=message):
            mint_access_token(session.as_session(), credentials())

    def test_token_is_reused_until_forced_to_refresh(self) -> None:
        session = FakeSession(
            post_responses=[
                FakeResponse(payload=TOKEN_PAYLOAD),
                FakeResponse(payload={**TOKEN_PAYLOAD, "access_token": "tok-2"}),
            ]
        )
        tokens = token_provider(session)

        assert tokens.token() == "tok-1"
        assert tokens.token() == "tok-1"
        assert tokens.token(force_refresh=True) == "tok-2"
        assert len(session.posts) == 2

    def test_expired_token_mid_sync_is_reminted_once(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[
                FakeResponse(status_code=401, payload={"error": {"status": "UNAUTHENTICATED"}}),
                FakeResponse(payload={"documents": [firestore_document("abc")]}),
            ],
            post_responses=[
                FakeResponse(payload=TOKEN_PAYLOAD),
                FakeResponse(payload={**TOKEN_PAYLOAD, "access_token": "tok-2"}),
            ],
        )

        batches = list(
            iter_firestore_documents(
                session.as_session(), token_provider(session), credentials(), "rooms", FakeResumeManager(), logger
            )
        )

        assert len(batches) == 1
        assert session.requests[1][2]["headers"] == {"Authorization": "Bearer tok-2"}


class TestFirestorePagination:
    def test_pages_and_checkpoints_after_each_yield(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[
                FakeResponse(payload={"documents": [firestore_document("a")], "nextPageToken": "page-2"}),
                FakeResponse(payload={"documents": [firestore_document("b")]}),
            ],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )
        manager = FakeResumeManager()

        batches = list(
            iter_firestore_documents(
                session.as_session(), token_provider(session), credentials(), "rooms", manager, logger
            )
        )

        assert [row[FIRESTORE_ID_COLUMN] for batch in batches for row in batch] == ["a", "b"]
        assert [state.cursor for state in manager.saved] == ["page-2"]
        assert manager.cleared is True
        assert session.requests[1][2]["params"]["pageToken"] == "page-2"

    def test_resumes_from_the_saved_page_token(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(payload={"documents": [firestore_document("c")]})],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        list(
            iter_firestore_documents(
                session.as_session(),
                token_provider(session),
                credentials(),
                "rooms",
                FakeResumeManager(FirebaseResumeConfig(cursor="page-9")),
                logger,
            )
        )

        assert session.requests[0][2]["params"]["pageToken"] == "page-9"

    def test_collection_id_is_url_escaped(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(payload={})], post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)]
        )

        list(
            iter_firestore_documents(
                session.as_session(), token_provider(session), credentials(), "chat rooms", FakeResumeManager(), logger
            )
        )

        assert session.requests[0][1] == f"{DOCUMENTS_ROOT}/chat%20rooms"

    def test_collection_ids_are_paged(self) -> None:
        session = FakeSession(
            request_responses=[
                FakeResponse(payload={"collectionIds": ["rooms"], "nextPageToken": "next"}),
                FakeResponse(payload={"collectionIds": ["users"]}),
            ],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        assert list_collection_ids(session.as_session(), token_provider(session), credentials()) == ["rooms", "users"]
        assert session.requests[0][1] == f"{DOCUMENTS_ROOT}:listCollectionIds"
        assert session.requests[1][2]["json"]["pageToken"] == "next"


class TestAuthUsersPagination:
    def test_stops_when_google_returns_no_token(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[
                FakeResponse(payload={"users": [{"localId": "u1"}], "nextPageToken": "p2"}),
                FakeResponse(payload={"users": [{"localId": "u2"}]}),
            ],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )
        manager = FakeResumeManager()

        batches = list(iter_auth_users(session.as_session(), token_provider(session), credentials(), manager, logger))

        assert [row["localId"] for batch in batches for row in batch] == ["u1", "u2"]
        assert [state.cursor for state in manager.saved] == ["p2"]
        assert session.requests[0][1].endswith("/projects/demo-project/accounts:batchGet")

    def test_stops_on_an_empty_page_even_when_a_token_is_returned(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(payload={"users": [], "nextPageToken": "p2"})],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        batches = list(
            iter_auth_users(session.as_session(), token_provider(session), credentials(), FakeResumeManager(), logger)
        )

        assert batches == []


class TestRealtimeDatabase:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://demo-default-rtdb.firebaseio.com", "https://demo-default-rtdb.firebaseio.com"),
            ("https://demo.europe-west1.firebasedatabase.app/", "https://demo.europe-west1.firebasedatabase.app"),
            (" https://Demo-Default-Rtdb.firebaseio.com ", "https://demo-default-rtdb.firebaseio.com"),
        ],
    )
    def test_accepts_firebase_hosts(self, url: str, expected: str) -> None:
        assert validate_realtime_database_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "http://demo-default-rtdb.firebaseio.com",
            "https://attacker.example.com",
            "https://firebaseio.com.attacker.example",
            "https://169.254.169.254",
            "not-a-url",
        ],
    )
    def test_rejects_everything_else(self, url: str) -> None:
        with pytest.raises(FirebaseConfigError):
            validate_realtime_database_url(url)

    def test_pages_by_key_and_drops_the_repeated_boundary_row(self, logger: FilteringBoundLogger) -> None:
        first_page = {f"k{index:04d}": {"n": index} for index in range(REALTIME_DATABASE_PAGE_SIZE)}
        last_key = f"k{REALTIME_DATABASE_PAGE_SIZE - 1:04d}"
        session = FakeSession(
            request_responses=[
                FakeResponse(payload=first_page),
                FakeResponse(payload={last_key: {"n": -1}, "k9999": {"n": 1}}),
            ],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )
        manager = FakeResumeManager()

        batches = list(
            iter_realtime_database(
                session.as_session(),
                token_provider(session),
                credentials(realtime_database_url="https://demo-default-rtdb.firebaseio.com"),
                "rooms",
                manager,
                logger,
            )
        )

        keys = [row[REALTIME_DATABASE_KEY_COLUMN] for batch in batches for row in batch]
        assert keys[-1] == "k9999"
        assert keys.count(last_key) == 1
        assert session.requests[0][2]["params"]["orderBy"] == '"$key"'
        assert session.requests[1][2]["params"]["startAt"] == json.dumps(last_key)
        assert [state.cursor for state in manager.saved] == [last_key]

    def test_scalar_node_yields_a_single_row(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(payload="online")], post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)]
        )

        batches = list(
            iter_realtime_database(
                session.as_session(),
                token_provider(session),
                credentials(realtime_database_url="https://demo-default-rtdb.firebaseio.com"),
                "status/global",
                FakeResumeManager(),
                logger,
            )
        )

        assert batches == [
            [
                {
                    REALTIME_DATABASE_VALUE_COLUMN: "online",
                    REALTIME_DATABASE_KEY_COLUMN: "global",
                    REALTIME_DATABASE_PATH_COLUMN: "status/global",
                }
            ]
        ]

    def test_array_node_uses_the_index_as_the_key(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(payload=[{"n": 0}, None, {"n": 2}])],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        batches = list(
            iter_realtime_database(
                session.as_session(),
                token_provider(session),
                credentials(realtime_database_url="https://demo-default-rtdb.firebaseio.com"),
                "rooms",
                FakeResumeManager(),
                logger,
            )
        )

        assert [row[REALTIME_DATABASE_KEY_COLUMN] for row in batches[0]] == ["0", "2"]

    def test_missing_url_is_a_config_error(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)])

        with pytest.raises(FirebaseConfigError, match="Realtime Database URL"):
            list(
                iter_realtime_database(
                    session.as_session(), token_provider(session), credentials(), "rooms", FakeResumeManager(), logger
                )
            )


class TestTableDiscovery:
    def test_lists_auth_firestore_and_configured_paths(self) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(payload={"collectionIds": ["rooms", "users"]})],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            tables = get_tables(
                credentials(
                    realtime_database_url="https://demo-default-rtdb.firebaseio.com",
                    realtime_database_paths=("rooms", "messages/lobby"),
                )
            )

        assert tables == [
            AUTH_USERS_TABLE,
            "firestore_rooms",
            "firestore_users",
            "realtime_database_rooms",
            "realtime_database_messages_lobby",
        ]

    @pytest.mark.parametrize("status", [403, 404])
    def test_unreachable_firestore_does_not_hide_the_other_tables(self, status: int) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(status_code=status, payload={"error": {"status": "PERMISSION_DENIED"}})],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            assert get_tables(credentials()) == [AUTH_USERS_TABLE]

    def test_other_firestore_errors_propagate(self) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(status_code=500, payload={"error": {"status": "INTERNAL"}})],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            with pytest.raises(requests.HTTPError):
                get_tables(credentials())


class TestSourceResponseShape:
    @pytest.mark.parametrize(
        "table_name,primary_keys,partitioned",
        [
            (AUTH_USERS_TABLE, ["localId"], False),
            ("firestore_rooms", [FIRESTORE_ID_COLUMN], True),
            ("realtime_database_rooms", [REALTIME_DATABASE_KEY_COLUMN], False),
        ],
    )
    def test_primary_keys_and_partitioning_match_the_table_kind(
        self, table_name: str, primary_keys: list[str], partitioned: bool, logger: FilteringBoundLogger
    ) -> None:
        response = firebase_source(credentials(), table_name, FakeResumeManager(), logger)

        assert response.name == table_name
        assert response.primary_keys == primary_keys
        assert (response.partition_mode == "datetime") is partitioned
        assert (response.partition_keys == [FIRESTORE_CREATE_TIME_COLUMN]) is partitioned

    def test_unknown_table_is_rejected(self, logger: FilteringBoundLogger) -> None:
        with mock.patch(_SESSION_FACTORY, return_value=FakeSession().as_session()):
            with pytest.raises(FirebaseConfigError, match="not configured"):
                list(get_rows(credentials(), "made_up_table", FakeResumeManager(), logger))


class TestCredentialValidation:
    def test_valid_key_mints_a_token(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)])

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            assert validate_credentials(credentials()) == (True, None)

    def test_rejected_key_reports_googles_reason(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(status_code=400, payload={"error": "invalid_grant"})])

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            valid, message = validate_credentials(credentials())

        assert valid is False
        assert message is not None and "invalid_grant" in message

    @pytest.mark.parametrize(
        "overrides,message",
        [
            (
                {"realtime_database_url": "https://attacker.example.com", "realtime_database_paths": ("rooms",)},
                "firebaseio.com",
            ),
            (
                {"realtime_database_url": "https://demo-default-rtdb.firebaseio.com"},
                "at least one Realtime Database path",
            ),
        ],
    )
    def test_realtime_database_settings_are_checked_before_any_request(
        self, overrides: dict[str, Any], message: str
    ) -> None:
        valid, reason = validate_credentials(credentials(**overrides))

        assert valid is False
        assert reason is not None and message in reason
