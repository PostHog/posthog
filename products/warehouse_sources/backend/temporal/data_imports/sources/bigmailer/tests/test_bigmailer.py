from typing import Any, cast

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.bigmailer import (
    AUTH_ERROR_MESSAGE,
    BigMailerAuthError,
    BigMailerResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.source import BigMailerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigmailer import (
    BigMailerSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(BigMailerSource(), BigMailerSourceConfig(api_key="key"))


def _page(items: list[dict[str, Any]], *, has_more: bool = False, cursor: str | None = None) -> ScriptedResponse:
    # The API always returns a `cursor`; only `has_more` tells us another page exists.
    return ScriptedResponse(
        json={"data": items, "has_more": has_more, "cursor": cursor if cursor is not None else "ignored"}
    )


class TestTopLevelPagination:
    def test_follows_cursor_until_has_more_false(self) -> None:
        result = _driver().run(
            "brands",
            [
                _page([{"id": "b1", "created": 1}], has_more=True, cursor="C2=="),
                _page([{"id": "b2", "created": 2}], has_more=False, cursor="ignored"),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["b1", "b2"]
        assert result.params("limit") == ["100", "100"]
        # second request must carry the cursor from page one
        assert result.params("cursor") == [None, "C2=="]
        assert len(result.requests) == 2

    def test_does_not_inject_brand_id_for_top_level(self) -> None:
        result = _driver().run("brands", [_page([{"id": "b1", "created": 1}])])

        assert result.raised is None
        assert "brand_id" not in result.rows[0]

    def test_saves_next_cursor_after_yielding_each_page(self) -> None:
        result = _driver().run("brands", [_page([{"id": "b1"}], has_more=True, cursor="C2=="), _page([{"id": "b2"}])])

        assert result.raised is None
        # one save (for the single page boundary that had a next page); none after the terminal page
        assert result.saved_states == [BigMailerResumeConfig(cursor="C2==")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "brands", [_page([{"id": "b2"}])], resume_state=BigMailerResumeConfig(cursor="RESUME==", brand_id=None)
        )

        assert result.raised is None
        assert result.params("cursor") == ["RESUME=="]


class TestBrandFanOut:
    def test_iterates_every_brand_and_injects_brand_id(self) -> None:
        result = _driver().run(
            "contacts",
            [
                _page([{"id": "b1"}, {"id": "b2"}]),  # /brands
                _page([{"id": "c1", "created": 1}]),  # b1 contacts
                _page([{"id": "c2", "created": 2}]),  # b2 contacts
            ],
        )

        assert result.raised is None
        assert [(row["id"], row["brand_id"]) for row in result.rows] == [("c1", "b1"), ("c2", "b2")]
        # the injected brand id must be the plain `brand_id` column, not the prefixed parent key
        assert result.rows[0] == {"id": "c1", "created": 1, "brand_id": "b1"}
        assert result.paths == ["/v1/brands", "/v1/brands/b1/contacts", "/v1/brands/b2/contacts"]

    def test_resume_skips_completed_brands_and_resumes_cursor(self) -> None:
        # Resuming mid-fan-out must not re-request brands completed before the crash, and must start
        # the in-progress brand from its saved cursor.
        result = _driver().run(
            "contacts",
            [
                _page([{"id": "b1"}, {"id": "b2"}, {"id": "b3"}]),  # /brands
                _page([{"id": "c2"}]),  # b2 contacts (resumed)
                _page([{"id": "c3"}]),  # b3 contacts (fresh)
            ],
            resume_state=BigMailerResumeConfig(
                fanout_state={
                    "completed": ["/brands/b1/contacts"],
                    "current": "/brands/b2/contacts",
                    "child_state": {"cursor": "MID=="},
                }
            ),
        )

        assert result.raised is None
        assert result.paths == ["/v1/brands", "/v1/brands/b2/contacts", "/v1/brands/b3/contacts"]
        assert result.params("cursor") == [None, "MID==", None]
        assert [row["id"] for row in result.rows] == ["c2", "c3"]

    def test_pre_migration_resume_state_starts_fresh(self) -> None:
        # An old-shape bookmark (cursor + brand_id, no fanout_state) can't be translated into the
        # framework's completed/current map — the fan-out restarts from the first brand instead.
        result = _driver().run(
            "contacts",
            [
                _page([{"id": "b1"}, {"id": "b2"}]),  # /brands
                _page([{"id": "c1"}]),  # b1 contacts
                _page([{"id": "c2"}]),  # b2 contacts
            ],
            resume_state=BigMailerResumeConfig(cursor="MID==", brand_id="b2"),
        )

        assert result.raised is None
        assert [(row["id"], row["brand_id"]) for row in result.rows] == [("c1", "b1"), ("c2", "b2")]
        assert result.params("cursor") == [None, None, None]

    def test_checkpoints_completed_brands(self) -> None:
        result = _driver().run(
            "contacts",
            [
                _page([{"id": "b1"}, {"id": "b2"}]),
                _page([{"id": "c1"}]),
                _page([{"id": "c2"}]),
            ],
        )

        assert result.raised is None
        # after finishing b1 a checkpoint marks it completed, so a crash resumes on b2, not b1
        assert any(
            state.fanout_state is not None and "/brands/b1/contacts" in state.fanout_state["completed"]
            for state in result.saved_states
        )


class TestResumeConfigCompatibility:
    def test_old_saved_state_still_parses(self) -> None:
        # ResumableSourceManager._load_json does dataclass(**saved) — state saved by the
        # pre-framework implementation must keep loading after the migration.
        state = BigMailerResumeConfig(**cast("dict[str, Any]", {"cursor": "C2==", "brand_id": "b1"}))
        assert state.cursor == "C2=="
        assert state.brand_id == "b1"
        assert state.fanout_state is None


class TestAuthErrors:
    @parameterized.expand(
        [
            ("invalid_key_400", 400, '{"message":"Invalid api key"}'),
            ("unauthorized_401", 401, ""),
            ("forbidden_403", 403, ""),
        ]
    )
    def test_auth_failures_raise_non_retryable(self, _name: str, status: int, text: str) -> None:
        result = _driver().run("brands", [ScriptedResponse(status=status, body=text.encode())])

        assert isinstance(result.raised, BigMailerAuthError)
        assert str(result.raised) == AUTH_ERROR_MESSAGE

    def test_auth_failure_on_a_brand_child_list_raises_non_retryable(self) -> None:
        result = _driver().run("contacts", [_page([{"id": "b1"}]), ScriptedResponse(status=401)])

        assert isinstance(result.raised, BigMailerAuthError)

    def test_non_auth_400_raises_http_error_not_auth_error(self) -> None:
        # A 400 that isn't about the api key (e.g. a malformed param) must not be misreported as a
        # credential problem — otherwise a transient request bug would permanently disable the source.
        result = _driver().run("brands", [ScriptedResponse(status=400, body=b'{"message":"bad cursor"}')])

        assert isinstance(result.raised, requests.HTTPError)

    def test_404_raises_http_error(self) -> None:
        result = _driver().run("brands", [ScriptedResponse(status=404, body=b"not found")])

        assert isinstance(result.raised, requests.HTTPError)


class TestValidateCredentials:
    @parameterized.expand([("invalid", 400, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("key") is expected

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/v1/brands"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["x-api-key"] == "key"


class TestSourceResponse:
    @parameterized.expand(
        [
            ("brands", ["id"]),
            ("users", ["id"]),
            ("contacts", ["brand_id", "id"]),
            ("bulk_campaigns", ["brand_id", "id"]),
            ("suppression_lists", ["brand_id", "id"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys
