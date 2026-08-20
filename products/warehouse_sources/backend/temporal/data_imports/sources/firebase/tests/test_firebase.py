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
    FirebaseResponseTooLargeError,
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
    JWT_ASSERTION_LIFETIME_SECONDS,
    OAUTH_SCOPES,
    REALTIME_DATABASE_KEY_COLUMN,
    REALTIME_DATABASE_PAGE_SIZE,
    REALTIME_DATABASE_PATH_COLUMN,
    REALTIME_DATABASE_VALUE_COLUMN,
    RESPONSE_TOO_LARGE_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.tests.conftest import (
    PUBLIC_KEY_PEM,
    TOKEN_PAYLOAD,
    FakeResponse,
    FakeResumeManager,
    FakeSession,
    credentials,
)

_FIREBASE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.firebase.firebase"
_SESSION_FACTORY = f"{_FIREBASE_MODULE}.make_tracked_session"

# Stand-ins for the shipped byte caps, small enough that a test can overflow one cheaply.
_PAGE_CAP = 2048
_ERROR_CAP = 64

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
            ({"doubleValue": "not-a-number"}, None),
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
            # A gateway can answer with HTML or an empty body; the status alone still has to surface.
            (FakeResponse(status_code=502), "status=502"),
            (FakeResponse(status_code=400, payload={"nothing": "useful"}), "status=400"),
            (FakeResponse(payload={"token_type": "Bearer"}), "did not contain an access token"),
        ],
    )
    def test_token_failures_raise_with_googles_reason(self, response: FakeResponse, message: str) -> None:
        session = FakeSession(post_responses=[response])

        with pytest.raises(FirebaseAuthError, match=message):
            mint_access_token(session.as_session(), credentials())

    @pytest.mark.parametrize(
        "body,expected_lifetime",
        [
            # A zero lifetime is a real answer, not a missing one: treating it as missing would
            # cache a dead token for an hour and turn every request into a 401.
            ({**TOKEN_PAYLOAD, "expires_in": 0}, 0),
            ({**TOKEN_PAYLOAD, "expires_in": 60}, 60),
            ({"access_token": "tok-1", "token_type": "Bearer"}, JWT_ASSERTION_LIFETIME_SECONDS),
            ({**TOKEN_PAYLOAD, "expires_in": "not-a-number"}, JWT_ASSERTION_LIFETIME_SECONDS),
        ],
    )
    def test_lifetime_falls_back_only_when_google_omits_it(self, body: Any, expected_lifetime: int) -> None:
        session = FakeSession(post_responses=[FakeResponse(payload=body)])

        assert mint_access_token(session.as_session(), credentials()) == ("tok-1", expected_lifetime)

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

    def test_a_resume_marker_with_no_state_behind_it_starts_from_the_beginning(
        self, logger: FilteringBoundLogger
    ) -> None:
        # `can_resume()` and `load_state()` are two round trips to the store, so a checkpoint that
        # is cleared between them is reachable. It has to read as "no cursor", not crash.
        class VanishingResumeManager(FakeResumeManager):
            def can_resume(self) -> bool:
                return True

        session = FakeSession(
            request_responses=[FakeResponse(payload={"documents": [firestore_document("a")]})],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        list(
            iter_firestore_documents(
                session.as_session(),
                token_provider(session),
                credentials(),
                "rooms",
                VanishingResumeManager(),
                logger,
            )
        )

        assert "pageToken" not in session.requests[0][2]["params"]

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

    def test_datastore_mode_database_does_not_hide_the_other_tables(self) -> None:
        session = FakeSession(
            request_responses=[
                FakeResponse(
                    status_code=400,
                    payload={
                        "error": {
                            "code": 400,
                            "status": "FAILED_PRECONDITION",
                            "message": "The Cloud Firestore API is not available for Firestore in Datastore Mode database.",
                        }
                    },
                )
            ],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            assert get_tables(credentials()) == [AUTH_USERS_TABLE]

    @pytest.mark.parametrize(
        "status,payload",
        [
            (500, {"error": {"status": "INTERNAL"}}),
            # A 400 for any other reason is a real, actionable failure and must not be conflated
            # with the Datastore-mode case above just because the status code matches.
            (400, {"error": {"status": "INVALID_ARGUMENT", "message": "Invalid pageToken."}}),
        ],
    )
    def test_other_firestore_errors_propagate(self, status: int, payload: dict[str, Any]) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(status_code=status, payload=payload)],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            with pytest.raises(requests.HTTPError):
                get_tables(credentials())


class TestSampleCapture:
    def test_auth_user_responses_never_reach_sample_capture(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(payload={"users": [{"localId": "u1", "passwordHash": "hash"}]})],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()) as factory:
            batches = list(get_rows(credentials(), AUTH_USERS_TABLE, FakeResumeManager(), logger))

        # The raw response carries password material that row-level redaction only removes
        # afterwards, so no session used for this table may capture a sample.
        assert [call.kwargs["capture"] for call in factory.call_args_list] == [False, False]
        assert "passwordHash" not in batches[0][0]

    def test_firestore_responses_are_still_captured(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(payload={"documents": [firestore_document("a")]})],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()) as factory:
            list(get_rows(credentials(), "firestore_rooms", FakeResumeManager(), logger))

        assert factory.call_args_list[-1].kwargs["capture"] is True


class TestResponseSizeCaps:
    """Bodies are read under a byte cap so one page can't spike a shared worker's memory.

    The real caps are patched down to a few kilobytes throughout: the behaviour under test is
    "stop reading at N bytes", and allocating 64 MiB per test to demonstrate it would be waste.
    """

    def test_pages_are_requested_as_streams_rather_than_buffered(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(payload={"documents": [firestore_document("a")]})],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            list(get_rows(credentials(), "firestore_rooms", FakeResumeManager(), logger))

        # Without stream=True, requests materialises the whole body before we get a chance to cap it.
        assert session.posts[0][1]["stream"] is True
        assert all(kwargs["stream"] is True for _, _, kwargs in session.requests)

    def test_an_oversized_page_is_rejected_instead_of_buffered(self, logger: FilteringBoundLogger) -> None:
        oversized = FakeResponse(body=b"x" * (_PAGE_CAP + 1))
        session = FakeSession(
            request_responses=[oversized],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            with mock.patch(f"{_FIREBASE_MODULE}.MAX_RESPONSE_BYTES", _PAGE_CAP):
                with pytest.raises(FirebaseResponseTooLargeError, match=RESPONSE_TOO_LARGE_ERROR):
                    list(get_rows(credentials(), "firestore_rooms", FakeResumeManager(), logger))

        # Never more than one byte past the cap, and the connection is released either way.
        assert oversized.raw.bytes_read == _PAGE_CAP + 1
        assert oversized.closed is True

    def test_a_page_that_exactly_fills_the_cap_is_still_accepted(self, logger: FilteringBoundLogger) -> None:
        # Whitespace is JSON-insignificant, so padding to the cap keeps the page parseable.
        page = json.dumps({"documents": [firestore_document("a")]}).encode()
        session = FakeSession(
            request_responses=[FakeResponse(body=page + b" " * (_PAGE_CAP - len(page)))],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            with mock.patch(f"{_FIREBASE_MODULE}.MAX_RESPONSE_BYTES", _PAGE_CAP):
                batches = list(get_rows(credentials(), "firestore_rooms", FakeResumeManager(), logger))

        assert [row[FIRESTORE_ID_COLUMN] for row in batches[0]] == ["a"]

    def test_an_oversized_token_body_is_rejected(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(body=b"x" * (_PAGE_CAP + 1))])

        with mock.patch(f"{_FIREBASE_MODULE}.MAX_TOKEN_RESPONSE_BYTES", _PAGE_CAP):
            with pytest.raises(FirebaseResponseTooLargeError, match=RESPONSE_TOO_LARGE_ERROR):
                mint_access_token(session.as_session(), credentials())

    def test_a_token_body_that_is_not_json_is_reported_as_an_auth_error(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(body=b"<html>maintenance window</html>")])

        with pytest.raises(FirebaseAuthError, match="could not be read as JSON"):
            mint_access_token(session.as_session(), credentials())

    @pytest.mark.parametrize("body", [b"[]", b'"tok-1"', b"null"], ids=["array", "string", "null"])
    def test_a_token_body_that_is_json_but_not_an_object_has_no_token(self, body: bytes) -> None:
        # `json.loads` is happy with any JSON value, so the object check is what stops a bare
        # array or string from reaching `.get("access_token")` and raising AttributeError.
        session = FakeSession(post_responses=[FakeResponse(body=body)])

        with pytest.raises(FirebaseAuthError, match="did not contain an access token"):
            mint_access_token(session.as_session(), credentials())

    def test_an_empty_body_is_treated_as_no_payload(self, logger: FilteringBoundLogger) -> None:
        # A 200 with no body at all is not JSON; it means the node holds nothing.
        session = FakeSession(
            request_responses=[FakeResponse(body=b"")],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )
        configured = credentials(
            realtime_database_url="https://demo-default-rtdb.firebaseio.com",
            realtime_database_paths=("rooms",),
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            assert list(get_rows(configured, "realtime_database_rooms", FakeResumeManager(), logger)) == []

    def test_a_huge_error_body_is_truncated_not_masking_the_status(self, logger: FilteringBoundLogger) -> None:
        # A 403 has to stay a 403 — it maps to an actionable "grant the service account a role"
        # message. Complaining about the body's size instead would bury that.
        failure = FakeResponse(status_code=403, body=b"x" * (_PAGE_CAP + 1))
        session = FakeSession(
            request_responses=[failure],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            with mock.patch(f"{_FIREBASE_MODULE}.MAX_ERROR_BODY_BYTES", _ERROR_CAP):
                with pytest.raises(requests.HTTPError, match="403"):
                    list(get_rows(credentials(), "firestore_rooms", FakeResumeManager(), logger))

        assert failure.raw.bytes_read == _ERROR_CAP
        assert failure.closed is True

    def test_a_huge_token_error_body_is_truncated_rather_than_masking_the_status(self) -> None:
        failure = FakeResponse(status_code=400, body=b"x" * (_PAGE_CAP + 1))
        session = FakeSession(post_responses=[failure])

        with mock.patch(f"{_FIREBASE_MODULE}.MAX_ERROR_BODY_BYTES", _ERROR_CAP):
            with pytest.raises(FirebaseAuthError, match="status=400"):
                mint_access_token(session.as_session(), credentials())

        assert failure.raw.bytes_read == _ERROR_CAP

    def test_the_body_of_a_retried_401_is_never_read(self, logger: FilteringBoundLogger) -> None:
        unauthorized = FakeResponse(status_code=401, payload={"error": {"status": "UNAUTHENTICATED"}})
        session = FakeSession(
            request_responses=[unauthorized, FakeResponse(payload={"documents": [firestore_document("a")]})],
            post_responses=[
                FakeResponse(payload=TOKEN_PAYLOAD),
                FakeResponse(payload={**TOKEN_PAYLOAD, "access_token": "tok-2"}),
            ],
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            batches = list(get_rows(credentials(), "firestore_rooms", FakeResumeManager(), logger))

        # The discarded 401 is closed without its body being pulled at all.
        assert unauthorized.raw.bytes_read == 0
        assert unauthorized.closed is True
        assert [row[FIRESTORE_ID_COLUMN] for row in batches[0]] == ["a"]


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

    def test_realtime_database_table_is_dispatched_by_its_configured_path(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            request_responses=[FakeResponse(payload={"k1": {"n": 1}})],
            post_responses=[FakeResponse(payload=TOKEN_PAYLOAD)],
        )
        configured = credentials(
            realtime_database_url="https://demo-default-rtdb.firebaseio.com",
            realtime_database_paths=("rooms",),
        )

        with mock.patch(_SESSION_FACTORY, return_value=session.as_session()):
            batches = list(get_rows(configured, "realtime_database_rooms", FakeResumeManager(), logger))

        assert [row[REALTIME_DATABASE_KEY_COLUMN] for row in batches[0]] == ["k1"]

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

    def test_unreachable_google_is_not_reported_as_a_bad_key(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")

        with mock.patch(_SESSION_FACTORY, return_value=session):
            valid, message = validate_credentials(credentials())

        assert valid is False
        assert message == "Could not reach Google with the provided Firebase service account key."

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
