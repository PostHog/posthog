from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.replicate import replicate
from products.warehouse_sources.sources.replicate.replicate import (
    ReplicateResumeConfig,
    _build_initial_url,
    _extract_items,
    _format_incremental_value,
    _next_url,
    _page_predates_cutoff,
    _sanitize_next_url,
    get_rows,
    replicate_source,
)
from products.warehouse_sources.sources.replicate.settings import REPLICATE_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: ReplicateResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ReplicateResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ReplicateResumeConfig | None:
        return self._state

    def save_state(self, data: ReplicateResumeConfig) -> None:
        self.saved.append(data)

    def safe_point(self) -> None:
        pass


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        # A +00:00 offset instead of the Z suffix would build a created_after value the API may reject.
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestResponseShapeExtraction:
    @parameterized.expand(
        [
            (
                "paginated_results",
                "predictions",
                {"results": [{"id": "p1"}, {"id": "p2"}], "next": "https://api.replicate.com/v1/predictions?cursor=c"},
                [{"id": "p1"}, {"id": "p2"}],
                "https://api.replicate.com/v1/predictions?cursor=c",
            ),
            ("paginated_last_page", "predictions", {"results": [{"id": "p3"}], "next": None}, [{"id": "p3"}], None),
            (
                "bare_array",
                "hardware",
                [{"name": "Nvidia T4 GPU", "sku": "gpu-t4"}],
                [{"name": "Nvidia T4 GPU", "sku": "gpu-t4"}],
                None,
            ),
            (
                "single_object",
                "account",
                {"username": "acme", "type": "organization"},
                [{"username": "acme", "type": "organization"}],
                None,
            ),
        ]
    )
    def test_extract_items_and_next(
        self, _name: str, endpoint: str, payload: Any, expected_items: list[dict], expected_next: str | None
    ) -> None:
        config = REPLICATE_ENDPOINTS[endpoint]
        assert _extract_items(payload, config) == expected_items
        assert _next_url(payload) == expected_next


class TestBuildInitialUrl:
    def test_predictions_first_sync_has_no_filter(self) -> None:
        url = _build_initial_url(
            REPLICATE_ENDPOINTS["predictions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert url == "https://api.replicate.com/v1/predictions"

    def test_trainings_never_gets_a_time_filter(self) -> None:
        # trainings exposes no server-side timestamp filter, so a created_after must never be added
        # (it would silently do nothing while implying incremental behavior).
        url = _build_initial_url(
            REPLICATE_ENDPOINTS["trainings"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert url == "https://api.replicate.com/v1/trainings"


class TestPagePredatesCutoff:
    @parameterized.expand(
        [
            ("all_older", ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"], True),
            ("some_newer", ["2026-01-01T00:00:00Z", "2026-05-01T00:00:00Z"], False),
            ("no_dates", [None, None], False),
        ]
    )
    def test_page_predates_cutoff(self, _name: str, timestamps: list[str | None], expected: bool) -> None:
        cutoff = datetime(2026, 3, 4, tzinfo=UTC)
        items = [{"created_at": ts} for ts in timestamps]
        assert _page_predates_cutoff(items, "created_at", cutoff) is expected


class TestSanitizeNextUrl:
    @parameterized.expand(
        [
            # The API can return an http:// next URL; following it verbatim would leak the bearer
            # token over plaintext, so it must be pinned back to the https origin.
            (
                "http_upgraded_to_https",
                "http://api.replicate.com/v1/predictions?cursor=c",
                "https://api.replicate.com/v1/predictions?cursor=c",
            ),
            (
                "https_preserved",
                "https://api.replicate.com/v1/predictions?cursor=c",
                "https://api.replicate.com/v1/predictions?cursor=c",
            ),
            # A cursor pointing at any other host is dropped rather than followed with the token.
            ("foreign_host_rejected", "https://evil.example.com/v1/predictions?cursor=c", None),
            ("none_passthrough", None, None),
        ]
    )
    def test_sanitize_next_url(self, _name: str, raw: str | None, expected: str | None) -> None:
        assert _sanitize_next_url(raw) == expected


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], endpoint: str, **incremental: Any
) -> tuple[list[dict], list[str]]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(replicate, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for page in get_rows(
        api_key="r8_test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **incremental,
    ):
        rows.extend(page)
    return rows, fetched


class TestGetRows:
    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        resume_url = "https://api.replicate.com/v1/trainings?cursor=resume"
        pages = {resume_url: {"results": [{"id": "t9"}], "next": None}}
        manager = _FakeResumableManager(ReplicateResumeConfig(next_url=resume_url))
        rows, fetched = _collect(manager, monkeypatch, pages, "trainings")

        assert rows == [{"id": "t9"}]
        assert fetched == [resume_url]

    def test_incremental_stops_once_a_page_predates_watermark(self, monkeypatch: Any) -> None:
        # Guards the re-walk-history cost bug: if the server drops created_after on cursor pages, the
        # desc walk must still terminate at the watermark instead of paging through all of history.
        cutoff = datetime(2026, 3, 4, tzinfo=UTC)
        initial = _build_initial_url(REPLICATE_ENDPOINTS["predictions"], True, cutoff)
        page2 = "https://api.replicate.com/v1/predictions?cursor=p2"
        page3 = "https://api.replicate.com/v1/predictions?cursor=p3"
        pages = {
            initial: {"results": [{"id": "a", "created_at": "2026-05-01T00:00:00Z"}], "next": page2},
            page2: {"results": [{"id": "b", "created_at": "2026-01-01T00:00:00Z"}], "next": page3},
            page3: {"results": [{"id": "c", "created_at": "2025-12-01T00:00:00Z"}], "next": None},
        }
        manager = _FakeResumableManager()
        rows, fetched = _collect(
            manager,
            monkeypatch,
            pages,
            "predictions",
            should_use_incremental_field=True,
            db_incremental_field_last_value=cutoff,
            incremental_field="created_at",
        )

        assert [r["id"] for r in rows] == ["a", "b"]
        assert fetched == [initial, page2]  # page3 never fetched

    def test_416_on_first_page_treated_as_empty(self, monkeypatch: Any) -> None:
        # Replicate returns 416 instead of an empty page for some requests that match nothing
        # (e.g. a created_after filter predating the account's data). The sync must finish with
        # zero rows rather than failing.
        def raise_416(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
            response = requests.Response()
            response.status_code = 416
            response.url = url
            raise requests.HTTPError(response=response)

        monkeypatch.setattr(replicate, "_fetch_page", raise_416)
        manager = _FakeResumableManager()

        rows = []
        for page in get_rows(
            api_key="r8_test",
            endpoint="predictions",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(page)

        assert rows == []
        assert manager.saved == []

    def test_416_mid_pagination_stops_like_a_last_page(self, monkeypatch: Any) -> None:
        page2 = "https://api.replicate.com/v1/trainings?cursor=p2"
        pages = {
            f"https://api.replicate.com/v1{REPLICATE_ENDPOINTS['trainings'].path}": {
                "results": [{"id": "t1"}],
                "next": page2,
            },
        }

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
            if url == page2:
                response = requests.Response()
                response.status_code = 416
                response.url = url
                raise requests.HTTPError(response=response)
            return pages[url]

        monkeypatch.setattr(replicate, "_fetch_page", fake_fetch)
        manager = _FakeResumableManager()

        rows = []
        for page in get_rows(
            api_key="r8_test",
            endpoint="trainings",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(page)

        assert rows == [{"id": "t1"}]

    def test_single_request_endpoints_do_not_paginate(self, monkeypatch: Any) -> None:
        cases = [
            ("hardware", [{"name": "Nvidia T4 GPU", "sku": "gpu-t4"}], [{"name": "Nvidia T4 GPU", "sku": "gpu-t4"}]),
            ("account", {"username": "acme", "type": "organization"}, [{"username": "acme", "type": "organization"}]),
        ]
        for endpoint, payload, expected in cases:
            base = f"https://api.replicate.com/v1{REPLICATE_ENDPOINTS[endpoint].path}"
            manager = _FakeResumableManager()
            rows, fetched = _collect(manager, monkeypatch, {base: payload}, endpoint)

            assert rows == expected
            assert fetched == [base]
            assert manager.saved == []


def _http_error(status: int, url: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response.url = url
    return requests.HTTPError(f"{status} Client Error for url: {url}", response=response)


class TestFanOut:
    def test_model_versions_fan_out_over_deployed_and_trained_models(self, monkeypatch: Any) -> None:
        base = "https://api.replicate.com/v1"
        trainings_page2 = f"{base}/trainings?cursor=t2"
        sdxl_page2 = f"{base}/models/stability-ai/sdxl/versions?cursor=v2"
        gone = f"{base}/models/acme/deleted-model/versions"
        pages: dict[str, Any] = {
            f"{base}/deployments": {
                "results": [{"owner": "acme", "name": "prod", "current_release": {"model": "acme/my-model"}}],
                "next": None,
            },
            f"{base}/trainings": {
                "results": [
                    {"id": "t1", "model": "stability-ai/sdxl", "output": {"version": "acme/my-model:abc"}},
                    {"id": "t2", "model": "acme/deleted-model", "output": None},
                ],
                "next": trainings_page2,
            },
            trainings_page2: {"results": [{"id": "t3", "model": "stability-ai/sdxl", "output": {}}], "next": None},
            f"{base}/models/acme/my-model/versions": {"results": [{"id": "abc"}], "next": None},
            f"{base}/models/stability-ai/sdxl/versions": {"results": [{"id": "v1"}], "next": sdxl_page2},
            sdxl_page2: {"results": [{"id": "v0"}], "next": None},
        }
        fetched: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
            fetched.append(url)
            if url == gone:
                raise _http_error(404, url)
            return pages[url]

        monkeypatch.setattr(replicate, "_fetch_page", fake_fetch)
        rows = [
            row
            for page in get_rows(
                api_key="r8_test",
                endpoint="model_versions",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
            for row in page
        ]

        assert rows == [
            {"id": "abc", "model_owner": "acme", "model_name": "my-model"},
            {"id": "v1", "model_owner": "stability-ai", "model_name": "sdxl"},
            {"id": "v0", "model_owner": "stability-ai", "model_name": "sdxl"},
        ]
        # Each referenced model is fetched once, however many deployments or trainings use it.
        assert fetched.count(f"{base}/models/stability-ai/sdxl/versions") == 1
        assert gone in fetched

    def test_model_versions_raise_non_skippable_child_errors(self, monkeypatch: Any) -> None:
        base = "https://api.replicate.com/v1"
        pages: dict[str, Any] = {
            f"{base}/deployments": {"results": [], "next": None},
            f"{base}/trainings": {"results": [{"id": "t1", "model": "acme/my-model"}], "next": None},
        }

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
            if url in pages:
                return pages[url]
            raise _http_error(401, url)

        monkeypatch.setattr(replicate, "_fetch_page", fake_fetch)
        with pytest.raises(requests.HTTPError):
            list(
                get_rows(
                    api_key="r8_test",
                    endpoint="model_versions",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )

    def test_collection_models_fan_out_tags_each_model_with_its_collection(self, monkeypatch: Any) -> None:
        base = "https://api.replicate.com/v1"
        collections_page2 = f"{base}/collections?cursor=c2"
        pages = {
            f"{base}/collections": {"results": [{"slug": "super-resolution"}], "next": collections_page2},
            collections_page2: {"results": [{"slug": "empty"}, {"slug": "image-to-text"}], "next": None},
            f"{base}/collections/super-resolution": {
                "slug": "super-resolution",
                "models": [{"owner": "acme", "name": "upscaler"}, {"owner": "acme", "name": "esrgan"}],
            },
            f"{base}/collections/empty": {"slug": "empty", "models": []},
            f"{base}/collections/image-to-text": {
                "slug": "image-to-text",
                "models": [{"owner": "acme", "name": "upscaler"}],
            },
        }
        rows, _ = _collect(_FakeResumableManager(), monkeypatch, pages, "collection_models")

        assert rows == [
            {"owner": "acme", "name": "upscaler", "collection_slug": "super-resolution"},
            {"owner": "acme", "name": "esrgan", "collection_slug": "super-resolution"},
            {"owner": "acme", "name": "upscaler", "collection_slug": "image-to-text"},
        ]

    def test_model_versions_resume_from_the_saved_model_and_page(self, monkeypatch: Any) -> None:
        base = "https://api.replicate.com/v1"
        resume_url = f"{base}/models/acme/b-model/versions?cursor=v2"
        pages: dict[str, Any] = {
            f"{base}/deployments": {"results": [], "next": None},
            f"{base}/trainings": {
                "results": [{"model": "acme/c-model"}, {"model": "acme/b-model"}, {"model": "acme/a-model"}],
                "next": None,
            },
            resume_url: {"results": [{"id": "b1"}], "next": None},
            f"{base}/models/acme/c-model/versions": {"results": [{"id": "c1"}], "next": None},
        }
        manager = _FakeResumableManager(ReplicateResumeConfig(next_url=resume_url, fan_out_parent="acme/b-model"))
        rows, fetched = _collect(manager, monkeypatch, pages, "model_versions")

        assert [r["id"] for r in rows] == ["b1", "c1"]
        assert f"{base}/models/acme/a-model/versions" not in fetched
        assert manager.saved[-1] == ReplicateResumeConfig(next_url=None, fan_out_parent="acme/c-model")

    def test_collection_models_resume_after_the_saved_collection(self, monkeypatch: Any) -> None:
        base = "https://api.replicate.com/v1"
        page2 = f"{base}/collections?cursor=c2"
        pages = {
            page2: {"results": [{"slug": "done"}, {"slug": "next"}], "next": None},
            f"{base}/collections/next": {"slug": "next", "models": [{"owner": "acme", "name": "m"}]},
        }
        manager = _FakeResumableManager(ReplicateResumeConfig(next_url=page2, fan_out_parent="done"))
        rows, fetched = _collect(manager, monkeypatch, pages, "collection_models")

        assert rows == [{"owner": "acme", "name": "m", "collection_slug": "next"}]
        assert fetched == [page2, f"{base}/collections/next"]
        assert manager.saved == [ReplicateResumeConfig(next_url=page2, fan_out_parent="next")]


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_retry_then_succeed(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status, ok=False)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"results": []}

        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(replicate._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = replicate._fetch_page(session, "https://api.replicate.com/v1/predictions", {}, MagicMock())

        assert result == {"results": []}
        assert session.get.call_count == 2

    def test_client_error_raises_immediately(self) -> None:
        # A 401/403 must surface (so get_non_retryable_errors can disable the source), not retry.
        response = requests.Response()
        response.status_code = 401
        response.url = "https://api.replicate.com/v1/predictions"

        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            replicate._fetch_page(session, "https://api.replicate.com/v1/predictions", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("predictions", ["id"], "created_at", "desc"),
            ("trainings", ["id"], "created_at", "desc"),
            ("deployments", ["owner", "name"], None, "desc"),
            ("models", ["owner", "name"], None, "desc"),
            ("hardware", ["sku"], None, "desc"),
            ("account", ["username"], None, "desc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, expected_pk: list[str], partition_key: str | None, sort_mode: str
    ) -> None:
        response = replicate_source(
            api_key="r8_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == sort_mode
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None
