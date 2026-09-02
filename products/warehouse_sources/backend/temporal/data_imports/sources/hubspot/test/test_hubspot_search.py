from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests.exceptions import (
    ChunkedEncodingError,
    JSONDecodeError as RequestsJSONDecodeError,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot import (
    HubspotResumeConfig,
    _backfill_associations_into_results,
    _batch_read_associations,
    _flatten_result,
    _iso_to_ms,
    _resolve_search_properties,
    get_rows_via_search,
    hubspot_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.settings import (
    HUBSPOT_API_VERSION_2026_03,
    HUBSPOT_API_VERSION_V3,
    HUBSPOT_ENDPOINTS,
    HUBSPOT_METADATA_ENDPOINTS,
    SEARCH_PAGE_SIZE,
    SEARCH_RESULT_CAP,
)


def _make_response(status: int, payload: dict[str, Any] | None = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.text = text
    response.json.return_value = payload or {}
    response.raise_for_status.side_effect = None if response.ok else Exception(f"HTTP {status}")
    return response


def _make_manager(can_resume: bool = False, resume_state: HubspotResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    return manager


def _search_page(results: list[dict[str, Any]], after: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"results": results}
    if after is not None:
        payload["paging"] = {"next": {"after": after}}
    return payload


def _result(id_: str, cursor_value_ms: int, cursor_prop: str = "hs_lastmodifieddate") -> dict[str, Any]:
    # Shape mirrors HubSpot's v3 search API response. Properties are ISO strings.
    iso = datetime.fromtimestamp(cursor_value_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return {
        "id": id_,
        "properties": {
            "hs_object_id": id_,
            cursor_prop: iso,
        },
        "updatedAt": iso,
        "createdAt": iso,
    }


@pytest.fixture(autouse=True)
def _stub_property_names():
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._get_property_names",
        return_value=[],
    ):
        yield


class TestFlattenResult:
    def test_flattens_properties_to_top_level(self) -> None:
        row = _flatten_result({"id": "1", "properties": {"name": "acme", "hs_object_id": "1"}})
        assert row["name"] == "acme"
        assert row["hs_object_id"] == "1"

    def test_preserves_id_when_absent_in_properties(self) -> None:
        row = _flatten_result({"id": "abc", "properties": {"foo": "bar"}})
        assert row["id"] == "abc"
        assert row["foo"] == "bar"

    def test_builds_association_values(self) -> None:
        row = _flatten_result(
            {
                "id": "1",
                "properties": {"hs_object_id": "1"},
                "associations": {"deals": {"results": [{"id": "9", "type": "contact_to_deal"}]}},
            }
        )
        assert row["deals"] == [{"value": "1", "deals_id": "9"}]

    def test_no_associations_returns_without_key(self) -> None:
        row = _flatten_result({"id": "1", "properties": {"hs_object_id": "1"}})
        assert "deals" not in row


class TestIsoToMs:
    def test_none(self) -> None:
        assert _iso_to_ms(None) is None

    def test_int(self) -> None:
        assert _iso_to_ms(1_700_000_000_000) == 1_700_000_000_000

    def test_datetime_aware(self) -> None:
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        assert _iso_to_ms(dt) == int(dt.timestamp() * 1000)

    def test_datetime_naive_treated_as_utc(self) -> None:
        naive = datetime(2024, 1, 15, 12, 0, 0)
        expected = int(naive.replace(tzinfo=UTC).timestamp() * 1000)
        assert _iso_to_ms(naive) == expected

    def test_iso_string_with_z(self) -> None:
        assert _iso_to_ms("2024-01-15T12:00:00.000Z") == int(
            datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC).timestamp() * 1000
        )

    def test_iso_string_with_offset(self) -> None:
        # +00:00 is equivalent to Z
        assert _iso_to_ms("2024-01-15T12:00:00.000+00:00") == int(
            datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC).timestamp() * 1000
        )

    def test_digit_string_passthrough(self) -> None:
        assert _iso_to_ms("1700000000000") == 1_700_000_000_000

    def test_invalid_string_returns_none(self) -> None:
        assert _iso_to_ms("not a date") is None


class TestResolveSearchProperties:
    def test_force_includes_required(self) -> None:
        props, expected = _resolve_search_properties(
            api_key="k",
            refresh_token="r",
            endpoint="deals",
            object_type="deal",
            selected_properties=["amount"],
            include_custom_props=False,
            required_props=["hs_lastmodifieddate", "hs_object_id"],
            logger=MagicMock(),
            source_id=None,
        )
        assert "hs_lastmodifieddate" in props
        assert "hs_object_id" in props
        assert "amount" in props
        assert expected == props

    def test_defaults_include_cursor(self) -> None:
        props, _ = _resolve_search_properties(
            api_key="k",
            refresh_token="r",
            endpoint="deals",
            object_type="deal",
            selected_properties=None,
            include_custom_props=False,
            required_props=["hs_lastmodifieddate", "hs_object_id"],
            logger=MagicMock(),
            source_id=None,
        )
        # DEFAULT_DEAL_PROPS already contains hs_lastmodifieddate and hs_object_id; no duplication
        assert props.count("hs_lastmodifieddate") == 1
        assert props.count("hs_object_id") == 1

    def test_no_duplicate_when_selected_already_contains_required(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._get_property_names",
            return_value=["amount", "hs_lastmodifieddate", "hs_object_id"],
        ):
            props, _ = _resolve_search_properties(
                api_key="k",
                refresh_token="r",
                endpoint="deals",
                object_type="deal",
                selected_properties=["amount", "hs_lastmodifieddate", "hs_object_id"],
                include_custom_props=False,
                required_props=["hs_lastmodifieddate", "hs_object_id"],
                logger=MagicMock(),
                source_id=None,
            )
        assert props.count("hs_lastmodifieddate") == 1
        assert props.count("hs_object_id") == 1

    def test_default_props_discover_custom_and_thread_version(self) -> None:
        # include_custom_props=True with no selection: non-hs_ custom props are appended,
        # and the pinned api_version reaches the property-discovery call.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._get_property_names",
            return_value=["amount", "hs_internal_only", "custom_field"],
        ) as get_names_mock:
            props, _ = _resolve_search_properties(
                api_key="k",
                refresh_token="r",
                endpoint="deals",
                object_type="deal",
                selected_properties=None,
                include_custom_props=True,
                required_props=["hs_lastmodifieddate", "hs_object_id"],
                logger=MagicMock(),
                source_id=None,
                api_version=HUBSPOT_API_VERSION_2026_03,
            )
        assert "custom_field" in props  # non-hs_ custom prop discovered and appended
        assert "hs_internal_only" not in props  # hs_ props are not auto-added
        assert get_names_mock.call_args.kwargs["api_version"] == HUBSPOT_API_VERSION_2026_03

    @pytest.mark.parametrize(
        "endpoint,object_type,discover_all,expect_hs_prop",
        [
            # Engagement and commerce objects keep almost everything behind hs_-prefixed
            # properties, so without discovery they sync only the two seeded columns.
            ("calls", "calls", True, True),
            ("line_items", "line_items", True, True),
            # The original objects ship hand-written default lists; auto-adding every hs_ property
            # would widen every existing customer's table.
            ("deals", "deal", False, False),
        ],
    )
    def test_discover_all_properties_controls_hs_prefixed_props(
        self, endpoint: str, object_type: str, discover_all: bool, expect_hs_prop: bool
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._get_property_names",
            return_value=["hs_call_duration", "custom_field"],
        ):
            props, _ = _resolve_search_properties(
                api_key="k",
                refresh_token="r",
                endpoint=endpoint,
                object_type=object_type,
                selected_properties=None,
                include_custom_props=True,
                required_props=["hs_lastmodifieddate", "hs_object_id"],
                logger=MagicMock(),
                source_id=None,
                api_version=HUBSPOT_API_VERSION_2026_03,
                discover_all_properties=discover_all,
            )

        assert ("hs_call_duration" in props) is expect_hs_prop
        assert "custom_field" in props
        assert HUBSPOT_ENDPOINTS[endpoint].discover_all_properties is discover_all

    def test_invalid_selected_ignored(self) -> None:
        logger = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._get_property_names",
            return_value=["amount"],
        ):
            props, _ = _resolve_search_properties(
                api_key="k",
                refresh_token="r",
                endpoint="deals",
                object_type="deal",
                selected_properties=["amount", "not_real"],
                include_custom_props=False,
                required_props=["hs_lastmodifieddate"],
                logger=logger,
                source_id=None,
            )
        assert "not_real" not in props
        assert "amount" in props
        logger.warning.assert_called()


class TestBatchReadAssociations:
    def test_empty_ids_returns_empty(self) -> None:
        result = _batch_read_associations(
            from_entity_plural="contacts",
            to_entity_plural="deals",
            ids=[],
            headers={"authorization": "Bearer x"},
            refresh_token="r",
            source_id=None,
            logger=MagicMock(),
            api_version=HUBSPOT_API_VERSION_V3,
        )
        assert result == {}

    def test_posts_correct_body(self) -> None:
        calls = []

        def _post(url, headers=None, json=None, timeout=None):  # noqa: ARG001
            calls.append({"url": url, "json": json})
            return _make_response(
                200,
                {"results": [{"from": {"id": "1"}, "to": [{"toObjectId": 9, "associationTypes": [{"label": "x"}]}]}]},
            )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(_post)})(),
        ):
            result = _batch_read_associations(
                from_entity_plural="contacts",
                to_entity_plural="deals",
                ids=["1", "2", "3"],
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
                api_version=HUBSPOT_API_VERSION_V3,
            )

        assert calls[0]["url"].endswith("/crm/v4/associations/contacts/deals/batch/read")
        assert calls[0]["json"] == {"inputs": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}
        assert result["1"] == [{"id": "9", "type": "x"}]

    @pytest.mark.parametrize(
        "api_version,expected_suffix",
        [
            (HUBSPOT_API_VERSION_V3, "/crm/v4/associations/contacts/deals/batch/read"),
            (HUBSPOT_API_VERSION_2026_03, "/crm/associations/2026-03/contacts/deals/batch/read"),
        ],
    )
    def test_url_carries_pinned_api_version(self, api_version: str, expected_suffix: str) -> None:
        calls = []

        def _post(url, headers=None, json=None, timeout=None):  # noqa: ARG001
            calls.append({"url": url})
            return _make_response(200, {"results": []})

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(_post)})(),
        ):
            _batch_read_associations(
                from_entity_plural="contacts",
                to_entity_plural="deals",
                ids=["1"],
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
                api_version=api_version,
            )

        assert calls[0]["url"].endswith(expected_suffix)

    def test_splits_into_chunks_of_batch_size(self) -> None:
        posts = []

        def _post(url, headers=None, json=None, timeout=None):  # noqa: ARG001
            posts.append(json)
            return _make_response(200, {"results": []})

        from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.settings import (
            ASSOCIATIONS_BATCH_SIZE,
        )

        ids = [str(i) for i in range(ASSOCIATIONS_BATCH_SIZE * 2 + 5)]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(_post)})(),
        ):
            _batch_read_associations(
                from_entity_plural="contacts",
                to_entity_plural="deals",
                ids=ids,
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
                api_version=HUBSPOT_API_VERSION_V3,
            )

        assert len(posts) == 3
        assert len(posts[0]["inputs"]) == ASSOCIATIONS_BATCH_SIZE
        assert len(posts[1]["inputs"]) == ASSOCIATIONS_BATCH_SIZE
        assert len(posts[2]["inputs"]) == 5

    def test_404_treated_as_empty(self) -> None:
        _resp = _make_response(404, {"message": "not found"})
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(lambda *a, **k: _resp)})(),
        ):
            result = _batch_read_associations(
                from_entity_plural="contacts",
                to_entity_plural="deals",
                ids=["1"],
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
                api_version=HUBSPOT_API_VERSION_V3,
            )
        assert result == {}


class TestBackfillAssociations:
    def test_noop_when_no_association_types(self) -> None:
        results = [{"id": "1"}]
        _backfill_associations_into_results(
            results=results,
            from_entity_plural="deals",
            association_types=[],
            headers={"authorization": "Bearer x"},
            refresh_token="r",
            source_id=None,
            logger=MagicMock(),
        )
        assert "associations" not in results[0]

    def test_hydrates_associations_in_v3_shape(self) -> None:
        results: list[dict[str, Any]] = [{"id": "1"}]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations",
            return_value={"1": [{"id": "9", "type": "x"}]},
        ):
            _backfill_associations_into_results(
                results=results,
                from_entity_plural="contacts",
                association_types=["deals"],
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
            )
        assert results[0]["associations"] == {"deals": {"results": [{"id": "9", "type": "x"}]}}

    def test_handles_missing_id_gracefully(self) -> None:
        # ids-less results just don't get associations attached; no crash
        results: list[dict[str, Any]] = [{}, {"id": "2"}]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations",
            return_value={"2": [{"id": "7", "type": "y"}]},
        ):
            _backfill_associations_into_results(
                results=results,
                from_entity_plural="contacts",
                association_types=["deals"],
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
            )
        assert results[1]["associations"]["deals"]["results"] == [{"id": "7", "type": "y"}]


# Freeze "now" across search tests so window math is deterministic.
_FIXED_NOW_MS = 1_800_000_000_000  # 2027-01-15 08:00 UTC-ish
# Default seed that's within one window of `_FIXED_NOW_MS` so tests only iterate one window
# unless they deliberately want more.
_RECENT_SEED_MS = _FIXED_NOW_MS - (10 * 24 * 60 * 60 * 1000)
_RECENT_SEED_ISO = datetime.fromtimestamp(_RECENT_SEED_MS / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _setup_search_post(responses: list[Any]) -> tuple[Callable[..., Any], list[dict[str, Any]]]:
    """Return (side_effect_callable, captured_requests)."""
    captured: list[dict[str, Any]] = []
    iter_responses = iter(responses)

    def _post(url, headers=None, json=None, timeout=None):  # noqa: ARG001
        captured.append({"url": url, "json": dict(json or {})})
        return next(iter_responses)

    return _post, captured


class TestGetRowsViaSearch:
    def test_single_window_single_page_no_associations(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        rows = [_result("1", 1_799_000_000_000), _result("2", 1_799_500_000_000)]
        side_effect, captured = _setup_search_post([_make_response(200, _search_page(rows))])

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        assert len(captured) == 1
        body = captured[0]["json"]
        assert body["sorts"] == [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}]
        assert body["limit"] == SEARCH_PAGE_SIZE
        assert body["filterGroups"][0]["filters"][0]["propertyName"] == "hs_lastmodifieddate"
        assert body["filterGroups"][0]["filters"][0]["operator"] == "GTE"
        assert body["filterGroups"][0]["filters"][1]["operator"] == "LTE"
        assert "after" not in body

    def test_seed_from_db_incremental_field_last_value(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, captured = _setup_search_post([_make_response(200, _search_page([]))])

        seed_iso = (
            datetime.fromtimestamp((_FIXED_NOW_MS - 5 * 24 * 60 * 60 * 1000) / 1000, tz=UTC).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3]
            + "Z"
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=seed_iso,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        seed_ms = _iso_to_ms(seed_iso)
        assert seed_ms is not None
        # First filter's GTE should be seed_ms + 1 so we don't re-include the last synced record
        gte = int(captured[0]["json"]["filterGroups"][0]["filters"][0]["value"])
        assert gte == seed_ms + 1

    def test_resume_from_search_state_overrides_seed(self) -> None:
        # Narrow window so only one request is needed for the remaining range.
        end = _FIXED_NOW_MS
        start = end - (5 * 24 * 60 * 60 * 1000)
        last = start + (2 * 24 * 60 * 60 * 1000)
        resume = HubspotResumeConfig(
            sync_start_ms=start,
            sync_end_ms=end,
            last_cursor_ms=last,
        )
        manager = _make_manager(can_resume=True, resume_state=resume)
        logger = MagicMock()
        side_effect, captured = _setup_search_post([_make_response(200, _search_page([]))])

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value="2024-01-01T00:00:00.000Z",  # ignored on resume
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS + 999_999_999,  # ignored on resume (sync_end_ms from state wins)
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        body = captured[0]["json"]
        assert int(body["filterGroups"][0]["filters"][0]["value"]) == last + 1  # last_cursor_ms + 1
        assert int(body["filterGroups"][0]["filters"][1]["value"]) == end  # sync_end_ms from state, not now_ms

    @pytest.mark.parametrize(
        "api_version,expected_suffix",
        [
            (HUBSPOT_API_VERSION_V3, "/crm/v3/objects/deals/search"),
            (HUBSPOT_API_VERSION_2026_03, "/crm/objects/2026-03/deals/search"),
        ],
    )
    def test_search_url_carries_pinned_api_version(self, api_version: str, expected_suffix: str) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, captured = _setup_search_post([_make_response(200, _search_page([]))])

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                    api_version=api_version,
                )
            )

        assert captured[0]["url"].endswith(expected_suffix)

    def test_ignores_next_url_resume_state(self) -> None:
        # A stale next_url from the GET path should not leak into the search path.
        resume = HubspotResumeConfig(next_url="https://stale.example/get")
        manager = _make_manager(can_resume=True, resume_state=resume)
        logger = MagicMock()
        side_effect, captured = _setup_search_post([_make_response(200, _search_page([]))])

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        # First request must start from STARTDATE (or equivalent), not the stale next_url.
        assert captured[0]["url"].endswith("/crm/v3/objects/deals/search")

    def test_multiple_windows_advance(self) -> None:
        # 90 days of range → 3 windows of 30 days.
        ninety_days_ms = 90 * 24 * 60 * 60 * 1000
        sync_end = _FIXED_NOW_MS
        sync_start_iso = (
            datetime.fromtimestamp((sync_end - ninety_days_ms) / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            + "Z"
        )

        manager = _make_manager()
        logger = MagicMock()
        # Three empty windows → three requests
        side_effect, captured = _setup_search_post(
            [
                _make_response(200, _search_page([])),
                _make_response(200, _search_page([])),
                _make_response(200, _search_page([])),
            ]
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=sync_start_iso,
                    include_custom_props=False,
                    now_ms=sync_end,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        assert len(captured) == 3
        # Lower bounds strictly ascending
        lowers = [int(c["json"]["filterGroups"][0]["filters"][0]["value"]) for c in captured]
        assert lowers[0] < lowers[1] < lowers[2]

    def test_pagination_via_after_within_window(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, captured = _setup_search_post(
            [
                _make_response(200, _search_page([_result("1", 1_799_000_000_000)], after="cursor-1")),
                _make_response(200, _search_page([_result("2", 1_799_500_000_000)])),
            ]
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        assert len(captured) == 2
        assert "after" not in captured[0]["json"]
        assert captured[1]["json"]["after"] == "cursor-1"

    def test_hits_10k_cap_and_subdivides(self) -> None:
        # Use cursor values within the seeded sync range so the fake server matches reality.
        cursor_base = _RECENT_SEED_MS + 10_000

        first_window_pages: list[dict[str, Any]] = []
        pages_in_cap = SEARCH_RESULT_CAP // SEARCH_PAGE_SIZE
        for i in range(pages_in_cap):
            batch = [
                _result(str(i * SEARCH_PAGE_SIZE + j), cursor_base + (i * SEARCH_PAGE_SIZE + j))
                for j in range(SEARCH_PAGE_SIZE)
            ]
            is_last = i == pages_in_cap - 1
            first_window_pages.append(_search_page(batch, after=None if is_last else f"c{i}"))

        # After the sub-slice kicks in, a small tail page with a record at a higher cursor.
        tail = [_result("tail-1", cursor_base + SEARCH_RESULT_CAP + 1_000)]
        responses = [_make_response(200, p) for p in first_window_pages] + [_make_response(200, _search_page(tail))]

        side_effect, captured = _setup_search_post(responses)
        manager = _make_manager()
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        assert len(captured) >= pages_in_cap + 1

        # The request immediately after the cap was reached must have no `after` token,
        # and its GTE must equal the max cursor seen in the capped sub-slice.
        subslice_request = captured[pages_in_cap]
        assert "after" not in subslice_request["json"]
        first_lower = int(captured[0]["json"]["filterGroups"][0]["filters"][0]["value"])
        subslice_lower = int(subslice_request["json"]["filterGroups"][0]["filters"][0]["value"])
        assert subslice_lower > first_lower
        assert subslice_lower == cursor_base + SEARCH_RESULT_CAP - 1

    def test_pathological_window_subdivides_by_hs_object_id(self) -> None:
        # SEARCH_RESULT_CAP records all share one cursor_ms (e.g. a bulk import stamping a
        # whole batch with the same lastmodifieddate) → can't sub-divide by cursor value, so
        # this must fall back to hs_object_id-based sub-slicing instead of dropping the sync.
        identical_cursor = 1_799_000_000_000
        pages_in_cap = SEARCH_RESULT_CAP // SEARCH_PAGE_SIZE
        pages = []
        for i in range(pages_in_cap):
            batch = [_result(str(i * SEARCH_PAGE_SIZE + j), identical_cursor) for j in range(SEARCH_PAGE_SIZE)]
            is_last = i == pages_in_cap - 1
            pages.append(_search_page(batch, after=None if is_last else f"c{i}"))

        # Only reachable once the id-anchored query subdivides past the cursor-sort cap.
        tail_id = str(SEARCH_RESULT_CAP + 1)
        tail = [_result(tail_id, identical_cursor)]

        responses = (
            [_make_response(200, p) for p in pages]
            + [_make_response(200, _search_page(tail))]  # id-drain page: the extra tied record
            + [_make_response(200, _search_page([]))]  # id-drain page: confirms exhaustion
            + [_make_response(200, _search_page([]))]  # window resumes past the tied cursor
        )
        side_effect, captured = _setup_search_post(responses)
        manager = _make_manager()
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            # Force a narrow sync window so the identical cursors trigger the cap check.
            tables = list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=str(identical_cursor - 1),
                    include_custom_props=False,
                    now_ms=identical_cursor + 1_000,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        # Every record is delivered, including the one only reachable past the cap.
        assert sum(t.num_rows for t in tables) == SEARCH_RESULT_CAP + 1

        drain_request = captured[pages_in_cap]["json"]
        assert drain_request["sorts"] == [{"propertyName": "hs_object_id", "direction": "ASCENDING"}]
        drain_filters = drain_request["filterGroups"][0]["filters"]
        assert {
            "propertyName": "hs_lastmodifieddate",
            "operator": "EQ",
            "value": str(identical_cursor),
        } in drain_filters
        assert {"propertyName": "hs_object_id", "operator": "GT", "value": "-1"} in drain_filters

        # The next id-drain query is anchored past the tail record just seen.
        second_drain_request = captured[pages_in_cap + 1]["json"]
        assert {
            "propertyName": "hs_object_id",
            "operator": "GT",
            "value": tail_id,
        } in second_drain_request["filterGroups"][0]["filters"]

    def test_pathological_window_drain_paginates_within_one_anchor_and_backfills_associations(
        self,
    ) -> None:
        # Regression: continuing a drain query via its `after` token must keep the same
        # hs_object_id GT anchor (HubSpot's `after` cursor is scoped to the filters it was
        # issued with) — only a *new* query after `after` runs out may advance the anchor.
        # Also covers contacts, the object type that actually hit this cap, to prove
        # association backfill still runs for records only reachable via the drain.
        identical_cursor = 1_799_000_000_000
        pages_in_cap = SEARCH_RESULT_CAP // SEARCH_PAGE_SIZE
        pages = []
        for i in range(pages_in_cap):
            batch = [
                _result(str(i * SEARCH_PAGE_SIZE + j), identical_cursor, cursor_prop="lastmodifieddate")
                for j in range(SEARCH_PAGE_SIZE)
            ]
            is_last = i == pages_in_cap - 1
            pages.append(_search_page(batch, after=None if is_last else f"c{i}"))

        drain_id_1 = str(SEARCH_RESULT_CAP + 1)
        drain_id_2 = str(SEARCH_RESULT_CAP + 2)
        drain_page_1 = [_result(drain_id_1, identical_cursor, cursor_prop="lastmodifieddate")]
        drain_page_2 = [_result(drain_id_2, identical_cursor, cursor_prop="lastmodifieddate")]

        responses = (
            [_make_response(200, p) for p in pages]
            + [_make_response(200, _search_page(drain_page_1, after="drain-1"))]  # anchor -1, page 1
            + [_make_response(200, _search_page(drain_page_2))]  # anchor -1, page 2 via `after`
            + [_make_response(200, _search_page([]))]  # fresh query, advanced anchor: exhausted
            + [_make_response(200, _search_page([]))]  # window resumes past the tied cursor
        )
        side_effect, captured = _setup_search_post(responses)
        manager = _make_manager()
        logger = MagicMock()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
                new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations",
                return_value={},
            ) as mock_batch,
        ):
            tables = list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="contacts",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=str(identical_cursor - 1),
                    include_custom_props=False,
                    now_ms=identical_cursor + 1_000,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        assert sum(t.num_rows for t in tables) == SEARCH_RESULT_CAP + 2

        # Second page of the first drain query: continues via `after`, anchor unchanged.
        continued_request = captured[pages_in_cap + 1]["json"]
        assert continued_request.get("after") == "drain-1"
        assert {"propertyName": "hs_object_id", "operator": "GT", "value": "-1"} in (
            continued_request["filterGroups"][0]["filters"]
        )

        # Once that query's `after` pages run out, a fresh query advances the anchor.
        restart_request = captured[pages_in_cap + 2]["json"]
        assert "after" not in restart_request
        assert {"propertyName": "hs_object_id", "operator": "GT", "value": drain_id_2} in (
            restart_request["filterGroups"][0]["filters"]
        )

        # Records only reachable via the drain still get their associations backfilled.
        assoc_ids_seen = {i for call in mock_batch.call_args_list for i in call.kwargs["ids"]}
        assert {drain_id_1, drain_id_2} <= assoc_ids_seen

    def test_drain_tied_cursor_restarts_anchor_before_paging_past_cap(self) -> None:
        # Regression: if a single hs_object_id anchor itself has more than SEARCH_RESULT_CAP
        # tied-cursor records, continuing to page it via `after` crosses HubSpot's per-query
        # cap and returns a 400 ("Attempting to page beyond 10,000"). The drain must restart
        # with an advanced anchor once it hits the cap, even though `after` still had more.
        identical_cursor = 1_799_000_000_000
        pages_in_cap = SEARCH_RESULT_CAP // SEARCH_PAGE_SIZE

        def _tied_pages(start_id: int, mark_more_after_last: bool) -> list[dict[str, Any]]:
            pages = []
            for i in range(pages_in_cap):
                batch = [
                    _result(str(start_id + i * SEARCH_PAGE_SIZE + j), identical_cursor) for j in range(SEARCH_PAGE_SIZE)
                ]
                is_last = i == pages_in_cap - 1
                after = f"c{i}" if not is_last or mark_more_after_last else None
                pages.append(_search_page(batch, after=after))
            return pages

        # First window sub-slice hits the cap with every record sharing one cursor value.
        window_pages = _tied_pages(start_id=0, mark_more_after_last=False)
        # The first drain anchor (-1) itself has more than SEARCH_RESULT_CAP tied records —
        # its last page still carries an `after` token, signalling more are available.
        anchor_pages = _tied_pages(start_id=SEARCH_RESULT_CAP, mark_more_after_last=True)
        max_anchor_id = SEARCH_RESULT_CAP + pages_in_cap * SEARCH_PAGE_SIZE - 1

        responses = (
            [_make_response(200, p) for p in window_pages]
            + [_make_response(200, p) for p in anchor_pages]
            + [_make_response(200, _search_page([]))]  # fresh query, advanced anchor: exhausted
            + [_make_response(200, _search_page([]))]  # window resumes past the tied cursor
        )
        side_effect, captured = _setup_search_post(responses)
        manager = _make_manager()
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            tables = list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=str(identical_cursor - 1),
                    include_custom_props=False,
                    now_ms=identical_cursor + 1_000,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        assert sum(t.num_rows for t in tables) == SEARCH_RESULT_CAP * 2

        # The request right after the anchor's own cap is hit must be a fresh query (no
        # `after`) anchored past the highest id seen — not a continuation of the anchor's
        # `after` token, even though that token was available.
        restart_request = captured[pages_in_cap * 2]["json"]
        assert "after" not in restart_request
        assert {
            "propertyName": "hs_object_id",
            "operator": "GT",
            "value": str(max_anchor_id),
        } in restart_request["filterGroups"][0]["filters"]

    def test_drain_tied_cursor_skips_records_with_non_numeric_id(self) -> None:
        # Defensive: a record with a missing/non-numeric id must not crash the drain — it's
        # still batched, just excluded from the id-anchor advance for that record.
        identical_cursor = 1_799_000_000_000
        pages_in_cap = SEARCH_RESULT_CAP // SEARCH_PAGE_SIZE
        pages = []
        for i in range(pages_in_cap):
            batch = [_result(str(i * SEARCH_PAGE_SIZE + j), identical_cursor) for j in range(SEARCH_PAGE_SIZE)]
            is_last = i == pages_in_cap - 1
            pages.append(_search_page(batch, after=None if is_last else f"c{i}"))

        bad_id_record = _result("not-a-number", identical_cursor)
        good_id_record = _result(str(SEARCH_RESULT_CAP + 1), identical_cursor)

        responses = (
            [_make_response(200, p) for p in pages]
            + [_make_response(200, _search_page([bad_id_record, good_id_record]))]
            + [_make_response(200, _search_page([]))]  # restart anchored past the good id
            + [_make_response(200, _search_page([]))]  # window resumes past the tied cursor
        )
        side_effect, captured = _setup_search_post(responses)
        manager = _make_manager()
        logger = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            tables = list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=str(identical_cursor - 1),
                    include_custom_props=False,
                    now_ms=identical_cursor + 1_000,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        # The bad-id record is still delivered; it just doesn't drive the anchor forward.
        assert sum(t.num_rows for t in tables) == SEARCH_RESULT_CAP + 2

        restart_request = captured[pages_in_cap + 1]["json"]
        assert {
            "propertyName": "hs_object_id",
            "operator": "GT",
            "value": str(SEARCH_RESULT_CAP + 1),
        } in restart_request["filterGroups"][0]["filters"]

    def test_saves_progress_at_window_boundaries(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, _ = _setup_search_post(
            [
                _make_response(200, _search_page([])),
                _make_response(200, _search_page([])),
            ]
        )

        sixty_days_ms = 60 * 24 * 60 * 60 * 1000
        sync_end = _FIXED_NOW_MS
        sync_start_iso = (
            datetime.fromtimestamp((sync_end - sixty_days_ms) / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            + "Z"
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=sync_start_iso,
                    include_custom_props=False,
                    now_ms=sync_end,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        # save_state should fire at least once per window advance
        assert manager.save_state.call_count >= 2
        last_saved = manager.save_state.call_args_list[-1].args[0]
        assert last_saved.sync_end_ms == sync_end
        assert last_saved.last_cursor_ms is not None and last_saved.last_cursor_ms >= last_saved.sync_start_ms

    def test_401_triggers_token_refresh_and_retry(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        responses = [
            _make_response(401, {"message": "unauthorized"}),
            _make_response(200, _search_page([])),
        ]
        side_effect, _ = _setup_search_post(responses)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
                new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.hubspot_refresh_access_token",
                return_value="new-token",
            ) as refresh,
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        refresh.assert_called_once()

    def test_backfills_associations_for_contacts(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        # One page of contacts with an id placed inside the valid sync window.
        side_effect, _ = _setup_search_post(
            [
                _make_response(
                    200,
                    _search_page([_result("1", _RECENT_SEED_MS + 10_000, cursor_prop="lastmodifieddate")]),
                )
            ]
        )

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
                new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations",
                return_value={"1": [{"id": "9", "type": "t"}]},
            ) as mock_batch,
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="contacts",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        # One call per association type configured on contacts (deals, tickets, quotes)
        assoc_types_called = {c.kwargs["to_entity_plural"] for c in mock_batch.call_args_list}
        assert assoc_types_called == {"deals", "tickets", "quotes"}
        from_types = {c.kwargs["from_entity_plural"] for c in mock_batch.call_args_list}
        assert from_types == {"contacts"}
        # Ids are passed through as strings
        assert mock_batch.call_args_list[0].kwargs["ids"] == ["1"]

    def test_no_association_backfill_for_deals(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, _ = _setup_search_post([_make_response(200, _search_page([_result("1", 1_799_000_000_000)]))])

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
                new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations"
            ) as mock_batch,
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        mock_batch.assert_not_called()

    def test_contacts_uses_lastmodifieddate_cursor(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, captured = _setup_search_post([_make_response(200, _search_page([]))])

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
                new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations",
                return_value={},
            ),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="contacts",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        body = captured[0]["json"]
        assert body["sorts"][0]["propertyName"] == "lastmodifieddate"
        assert body["filterGroups"][0]["filters"][0]["propertyName"] == "lastmodifieddate"


class TestHubspotSourceRouting:
    def test_search_path_requires_cursor_property(self) -> None:
        # Temporarily strip the cursor property from `deals` config to exercise the guard.
        no_cursor = replace(HUBSPOT_ENDPOINTS["deals"], cursor_filter_property_field=None)
        with patch.dict(HUBSPOT_ENDPOINTS, {"deals": no_cursor}), pytest.raises(ValueError):
            hubspot_source(
                api_key="k",
                refresh_token="r",
                endpoint="deals",
                logger=MagicMock(),
                resumable_source_manager=MagicMock(),
                use_search_path=True,
                api_version=HUBSPOT_API_VERSION_V3,
            )

    def test_search_path_happy_path(self) -> None:
        resp = hubspot_source(
            api_key="k",
            refresh_token="r",
            endpoint="deals",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
            use_search_path=True,
            db_incremental_field_last_value=None,
            api_version=HUBSPOT_API_VERSION_V3,
        )
        # SourceResponse should be returned with partition settings preserved.
        assert resp.name == "deals"
        assert resp.primary_keys == ["id"]
        assert resp.partition_keys == [HUBSPOT_ENDPOINTS["deals"].partition_key]

    def test_get_path_fallback(self) -> None:
        resp = hubspot_source(
            api_key="k",
            refresh_token="r",
            endpoint="deals",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
            use_search_path=False,
            api_version=HUBSPOT_API_VERSION_V3,
        )
        assert resp.name == "deals"

    @pytest.mark.parametrize("endpoint", list(HUBSPOT_METADATA_ENDPOINTS))
    def test_lookup_tables_bypass_the_crm_paths(self, endpoint: str) -> None:
        # Lookup tables aren't in HUBSPOT_ENDPOINTS, so routing them through the CRM paths raises
        # KeyError. Their keys are also composite: falling back to ["id"] would let the deals and
        # tickets "default" pipelines overwrite each other on merge.
        resp = hubspot_source(
            api_key="k",
            refresh_token="r",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
            use_search_path=False,
            api_version=HUBSPOT_API_VERSION_V3,
        )

        assert resp.name == endpoint
        assert resp.primary_keys == HUBSPOT_METADATA_ENDPOINTS[endpoint].primary_keys
        assert resp.partition_mode is None


class TestGetRowsFullRefresh:
    """Smoke test that the GET path still works alongside the search path."""

    def test_paginates_via_next_url(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot import get_rows

        manager = _make_manager()
        logger = MagicMock()

        page1 = {
            "results": [{"id": "1", "properties": {"hs_object_id": "1"}}],
            "paging": {"next": {"link": "https://api.hubapi.com/page2"}},
        }
        page2 = {"results": [{"id": "2", "properties": {"hs_object_id": "2"}}]}

        iter_resp = iter([_make_response(200, page1), _make_response(200, page2)])
        captured_urls: list[str] = []

        def _get(url, headers=None, timeout=None):  # noqa: ARG001
            captured_urls.append(url)
            return next(iter_resp)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"get": staticmethod(_get)})(),
        ):
            list(
                get_rows(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    include_custom_props=False,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        # Two calls: the constructed initial URL and the next_url from paging.
        assert len(captured_urls) == 2
        assert captured_urls[1] == "https://api.hubapi.com/page2"

    def test_resume_from_next_url(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot import get_rows

        resume = HubspotResumeConfig(next_url="https://api.hubapi.com/resume-here")
        manager = _make_manager(can_resume=True, resume_state=resume)
        logger = MagicMock()

        captured_urls: list[str] = []

        def _get(url, headers=None, timeout=None):  # noqa: ARG001
            captured_urls.append(url)
            return _make_response(200, {"results": [{"id": "5", "properties": {"hs_object_id": "5"}}]})

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"get": staticmethod(_get)})(),
        ):
            list(
                get_rows(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    include_custom_props=False,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        assert captured_urls[0] == "https://api.hubapi.com/resume-here"

    def test_truncated_json_body_is_retried(self) -> None:
        # Regression: a truncated/partial page body raises requests' JSONDecodeError
        # ("Unterminated string"). It must be treated as transient and retried, not crash
        # the whole import.
        from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot import get_rows

        manager = _make_manager()
        logger = MagicMock()

        truncated = _make_response(200, {"results": [{"id": "1", "properties": {"hs_object_id": "1"}}]})
        truncated.json.side_effect = RequestsJSONDecodeError("Unterminated string starting at", "doc", 42)
        good = _make_response(200, {"results": [{"id": "1", "properties": {"hs_object_id": "1"}}]})

        iter_resp = iter([truncated, good])
        captured_urls: list[str] = []

        def _get(url, headers=None, timeout=None):  # noqa: ARG001
            captured_urls.append(url)
            return next(iter_resp)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"get": staticmethod(_get)})(),
        ):
            tables = list(
                get_rows(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    include_custom_props=False,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        # The truncated response was reissued (same URL) and the retry yielded the row.
        assert len(captured_urls) == 2
        assert captured_urls[0] == captured_urls[1]
        assert sum(t.num_rows for t in tables) == 1

    def test_chunked_encoding_error_is_retried(self) -> None:
        # Regression: a connection dropped mid-stream (server closes early during chunked
        # transfer) raises requests' ChunkedEncodingError, which isn't a ConnectionError
        # subclass. It must be treated as transient and retried, not crash the whole import.
        from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot import get_rows

        manager = _make_manager()
        logger = MagicMock()

        good = _make_response(200, {"results": [{"id": "1", "properties": {"hs_object_id": "1"}}]})
        responses = iter([ChunkedEncodingError("Connection broken"), good])
        captured_urls: list[str] = []

        def _get(url, headers=None, timeout=None):  # noqa: ARG001
            captured_urls.append(url)
            next_response = next(responses)
            if isinstance(next_response, Exception):
                raise next_response
            return next_response

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"get": staticmethod(_get)})(),
        ):
            tables = list(
                get_rows(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    include_custom_props=False,
                    api_version=HUBSPOT_API_VERSION_V3,
                )
            )

        # The dropped connection was retried (same URL) and the second attempt yielded the row.
        assert len(captured_urls) == 2
        assert captured_urls[0] == captured_urls[1]
        assert sum(t.num_rows for t in tables) == 1


class TestExpectedPropertiesBackfill:
    def test_cursor_column_present_on_row_after_flatten(self) -> None:
        # The pipeline tracks the cursor column by reading a field from the flattened row.
        # Assert that after _flatten_result, the cursor property sits at the top level.
        r = _result("1", 1_800_000_000_000, cursor_prop="hs_lastmodifieddate")
        row = _flatten_result(r)
        assert "hs_lastmodifieddate" in row

        contact = _result("2", 1_800_000_000_000, cursor_prop="lastmodifieddate")
        row2 = _flatten_result(contact)
        assert "lastmodifieddate" in row2
