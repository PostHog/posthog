from datetime import date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.buttondown import (
    BUTTONDOWN_BASE_URL,
    ButtondownResumeConfig,
    _to_start_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.settings import BUTTONDOWN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source import ButtondownSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buttondown import (
    ButtondownSourceConfig,
)


def _page(
    results: list[dict[str, Any]] | None, next_url: str | None = None, *, drop_results: bool = False
) -> ScriptedResponse:
    body: dict[str, Any] = {"count": 1, "next": next_url, "previous": None}
    if not drop_results:
        body["results"] = results or []
    return ScriptedResponse(json=body)


class TestButtondownTransport:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(ButtondownSource(), ButtondownSourceConfig(api_key="bd-key"))

    def test_checkpoints_only_while_a_next_page_remains(self) -> None:
        page_two = f"{BUTTONDOWN_BASE_URL}/subscribers?page=2"
        result = self._driver().run(
            "subscribers",
            [_page([{"id": "a"}], next_url=page_two), _page([{"id": "b"}], next_url=None)],
        )

        assert result.raised is None
        assert result.rows == [{"id": "a"}, {"id": "b"}]
        assert result.saved_states == [ButtondownResumeConfig(next_url=page_two)]

    def test_notes_is_a_plain_full_refresh_listing(self) -> None:
        result = self._driver().run("notes", [_page([{"id": "note_1"}, {"id": "note_2"}])])

        assert result.raised is None
        assert result.urls[0].startswith(f"{BUTTONDOWN_BASE_URL}/notes")
        assert [row["id"] for row in result.rows] == ["note_1", "note_2"]

    def test_resumes_from_saved_next_url(self) -> None:
        saved = f"{BUTTONDOWN_BASE_URL}/subscribers?page=7"
        result = self._driver().run(
            "subscribers",
            [_page([{"id": "z"}], next_url=None)],
            resume_state=ButtondownResumeConfig(next_url=saved),
        )

        assert result.raised is None
        assert result.urls == [saved]
        assert [row["id"] for row in result.rows] == ["z"]

    @pytest.mark.parametrize(
        "endpoint,expected_param",
        [
            ("subscribers", "date__start"),
            ("emails", "creation_date__start"),
            ("survey_responses", "creation_date__start"),
        ],
    )
    def test_incremental_sync_sends_the_server_side_date_filter(self, endpoint: str, expected_param: str) -> None:
        result = self._driver().run(
            endpoint,
            [_page([{"id": "a"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 15, 30),
        )

        assert result.raised is None
        # One day back from the watermark: the docs don't say whether the bound is inclusive, and
        # overlapping rows merge away while a missed day would be silent data loss.
        assert result.requests[0].param(expected_param) == "2026-03-03"

    @pytest.mark.parametrize("endpoint", ["subscribers", "emails", "survey_responses"])
    def test_full_refresh_sends_no_date_filter(self, endpoint: str) -> None:
        result = self._driver().run(
            endpoint,
            [_page([{"id": "a"}])],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4),
        )

        assert result.raised is None
        assert not [key for key in result.requests[0].query if key.endswith("__start")]

    @pytest.mark.parametrize("endpoint", ["subscribers", "emails", "survey_responses"])
    @pytest.mark.parametrize("watermark", [None, "not-a-date"], ids=["missing", "unparseable"])
    def test_incremental_without_a_usable_watermark_sends_no_date_filter(self, endpoint: str, watermark: Any) -> None:
        # The first incremental run has no stored cursor, and a bad cursor converts to None. Either
        # way the filter must be dropped so the request backfills instead of asking for `__start=None`.
        result = self._driver().run(
            endpoint,
            [_page([{"id": "a"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert not [key for key in result.requests[0].query if key.endswith("__start")]

    @pytest.mark.parametrize(
        "endpoint",
        sorted(name for name, config in BUTTONDOWN_ENDPOINTS.items() if config.incremental_start_param),
    )
    def test_ascending_sort_mode_is_backed_by_an_explicit_ordering(self, endpoint: str) -> None:
        config = BUTTONDOWN_ENDPOINTS[endpoint]

        # An "asc" watermark is checkpointed after every batch, so it is only safe when the request
        # forces ascending order. Anything else must stay on the end-of-job commit path.
        assert config.sort_mode == "desc" or config.ordering == "creation_date"

    @pytest.mark.parametrize(
        "endpoint,child_suffix,parent_key,child_row",
        [
            ("stripe_subscriptions", "stripe-subscriptions", "subscriber_id", {"subscription_id": "sub_1"}),
            ("referrals", "referrals", "referrer_subscriber_id", {"id": "sub_referred"}),
            ("automation_attempts", "automations", "subscriber_id", {"id": "aut_att_1"}),
        ],
    )
    def test_fanout_walks_every_subscriber_and_keys_rows_by_the_parent(
        self, endpoint: str, child_suffix: str, parent_key: str, child_row: dict[str, Any]
    ) -> None:
        def child(subscriber: str) -> str:
            return f"/subscribers/{subscriber}/{child_suffix}"

        script = route(
            {
                child("sub_a"): [
                    _page([child_row], next_url=f"{BUTTONDOWN_BASE_URL}{child('sub_a')}?page=2"),
                    _page([{**child_row, "page": 2}]),
                ],
                # Deleted between the parent listing and its child fetch.
                child("sub_b"): [ScriptedResponse(status=404, json={"detail": "Not found."})],
                child("sub_c"): [_page([child_row])],
                "/subscribers": [
                    _page([{"id": "sub_a"}], next_url=f"{BUTTONDOWN_BASE_URL}/subscribers?page=2"),
                    _page([{"id": "sub_b"}, {"id": "sub_c"}]),
                ],
            }
        )

        result = self._driver().run(endpoint, script)

        assert result.raised is None
        assert result.rows == [
            {**child_row, parent_key: "sub_a"},
            {**child_row, "page": 2, parent_key: "sub_a"},
            {**child_row, parent_key: "sub_c"},
        ]
        assert result.response is not None and result.response.primary_keys is not None
        assert parent_key in result.response.primary_keys

    def test_fanout_resumes_from_the_subscriber_in_progress(self) -> None:
        in_progress_next = f"{BUTTONDOWN_BASE_URL}/subscribers/sub_b/referrals?page=3"
        script = route(
            {
                "/subscribers/sub_b/referrals": [_page([{"id": "sub_x"}])],
                "/subscribers/sub_c/referrals": [_page([{"id": "sub_y"}])],
                "/subscribers": [_page([{"id": "sub_a"}, {"id": "sub_b"}, {"id": "sub_c"}])],
            }
        )

        result = self._driver().run(
            "referrals",
            script,
            resume_state=ButtondownResumeConfig(
                fanout_state={
                    "completed": ["/subscribers/sub_a/referrals"],
                    "current": "/subscribers/sub_b/referrals",
                    "child_state": {"next_url": in_progress_next},
                }
            ),
        )

        assert result.raised is None
        assert result.urls[1:] == [in_progress_next, f"{BUTTONDOWN_BASE_URL}/subscribers/sub_c/referrals"]
        assert [row["referrer_subscriber_id"] for row in result.rows] == ["sub_b", "sub_c"]
        assert result.final_state.fanout_state["completed"] == [
            "/subscribers/sub_a/referrals",
            "/subscribers/sub_b/referrals",
            "/subscribers/sub_c/referrals",
        ]

    def test_missing_results_key_fails_loudly(self) -> None:
        result = self._driver().run("subscribers", [_page(None, drop_results=True)])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestToStartDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 15, 30), "2026-03-03"),
            (date(2026, 3, 4), "2026-03-03"),
            ("2026-03-04T15:30:00Z", "2026-03-03"),
            ("2026-03-04", "2026-03-03"),
            ("2026-03-01", "2026-02-28"),
            (None, None),
            ("not-a-date", None),
        ],
    )
    def test_formats_watermarks_as_dates(self, value: Any, expected: str | None) -> None:
        assert _to_start_date(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected",
        [(403, (False, 403))],
    )
    def test_maps_probe_status_to_result(self, status_code: int, expected: tuple[bool, int]) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("bd-key") == expected

        assert network.requests_log[0].path == "/v1/accounts/me"
        assert network.requests_log[0].headers["authorization"] == "Token bd-key"
        assert network.requests_log[0].headers["x-api-version"] == "2026-04-01"
