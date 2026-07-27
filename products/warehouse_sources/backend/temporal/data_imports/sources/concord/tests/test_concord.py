from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.concord import concord
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.concord import (
    ConcordResumeConfig,
    _agreement_incremental_params,
    _flatten_folder_tree,
    _iter_events_windows,
    _iter_page,
    _to_epoch_ms,
    base_url_for_environment,
    concord_source,
    get_rows,
    resolve_organization_id,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.settings import CONCORD_ENDPOINTS


class FakeManager(ResumableSourceManager[ConcordResumeConfig]):
    """In-memory stand-in for ResumableSourceManager so transport tests stay off Redis."""

    def __init__(self, state: ConcordResumeConfig | None = None):
        self._state = state
        self.saved: list[ConcordResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ConcordResumeConfig | None:
        return self._state

    def save_state(self, data: ConcordResumeConfig) -> None:
        self.saved.append(data)


def _collect(generator) -> list[dict[str, Any]]:
    """Flatten the pyarrow tables a transport generator yields into plain row dicts."""
    rows: list[dict[str, Any]] = []
    for table in generator:
        rows.extend(table.to_pylist())
    return rows


def _run(
    endpoint: str,
    payloads: list[Any],
    *,
    manager: FakeManager | None = None,
    organization_id: str | None = "42",
    **kwargs,
):
    """Drive get_rows with _fetch stubbed to return `payloads` in order; record requested URLs."""
    urls: list[str] = []
    manager = manager or FakeManager()

    def fake_fetch(session, url, headers, logger):
        urls.append(url)
        return payloads[min(len(urls) - 1, len(payloads) - 1)]

    with mock.patch.object(concord, "_fetch", side_effect=fake_fetch):
        rows = _collect(
            get_rows(
                api_key="key",
                environment="production",
                organization_id=organization_id,
                endpoint=endpoint,
                logger=mock.MagicMock(),
                manager=manager,
                **kwargs,
            )
        )
    return rows, urls, manager


class TestToEpochMs:
    @parameterized.expand(
        [
            ("none", None, None),
            ("datetime_utc", datetime(2024, 1, 1, tzinfo=UTC), 1704067200000),
            ("naive_datetime", datetime(2024, 1, 1), 1704067200000),
            ("date", date(2024, 1, 1), 1704067200000),
            ("int_passthrough", 1700000000000, 1700000000000),
            ("float", 1700000000000.0, 1700000000000),
        ]
    )
    def test_to_epoch_ms(self, _name, value, expected):
        assert _to_epoch_ms(value) == expected


class TestBaseUrl:
    @parameterized.expand(
        [
            ("production", "production", "https://api.concordnow.com/api/rest/1"),
            ("sandbox", "sandbox", "https://uat.concordnow.com/api/rest/1"),
            ("none_defaults_to_production", None, "https://api.concordnow.com/api/rest/1"),
            ("unknown_defaults_to_production", "staging", "https://api.concordnow.com/api/rest/1"),
        ]
    )
    def test_base_url_for_environment(self, _name, environment, expected):
        assert base_url_for_environment(environment) == expected


class TestFlattenFolderTree:
    def test_flattens_nested_tree_to_one_row_per_folder(self):
        root = {
            "id": 1,
            "name": "root",
            "parentId": None,
            "children": [
                {"id": 2, "name": "a", "parentId": 1, "children": []},
                {
                    "id": 3,
                    "name": "b",
                    "parentId": 1,
                    "children": [{"id": 4, "name": "c", "parentId": 3, "children": []}],
                },
            ],
        }
        rows = list(_flatten_folder_tree(root))
        assert [r["id"] for r in rows] == [1, 2, 3, 4]
        # children arrays are dropped so the warehouse row stays flat
        assert all("children" not in r for r in rows)
        assert rows[3]["parentId"] == 3

    def test_skips_nodes_without_id(self):
        assert list(_flatten_folder_tree({"name": "no id", "children": []})) == []


class TestAgreementIncrementalParams:
    @parameterized.expand(
        [
            ("modified", "modifiedAt", 1700000000000, {"modifiedAt.from": 1700000000000}),
            ("created", "createdAt", 1700000000000, {"createdAt.from": 1700000000000}),
            ("unknown_field_defaults_to_modified", "weird", 1700000000000, {"modifiedAt.from": 1700000000000}),
            ("no_value", "modifiedAt", None, {}),
        ]
    )
    def test_agreement_incremental_params(self, _name, field, value, expected):
        assert _agreement_incremental_params(field, value) == expected


class TestResolveOrganizationId:
    def test_uses_configured_org_id_without_request(self):
        session = mock.MagicMock()
        with mock.patch.object(concord, "_fetch") as fetch:
            assert resolve_organization_id(session, "https://x", "key", "123", mock.MagicMock()) == "123"
            fetch.assert_not_called()

    def test_resolves_first_org_when_blank(self):
        session = mock.MagicMock()
        with mock.patch.object(concord, "_fetch", return_value={"organizations": [{"id": 99}, {"id": 100}]}):
            assert resolve_organization_id(session, "https://x", "key", None, mock.MagicMock()) == "99"

    def test_raises_when_no_org_accessible(self):
        session = mock.MagicMock()
        with mock.patch.object(concord, "_fetch", return_value={"organizations": []}):
            with pytest.raises(ValueError, match="No Concord organizations"):
                resolve_organization_id(session, "https://x", "key", "", mock.MagicMock())


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_validate_credentials_status_mapping(self, _name, status_code, expected):
        session = mock.MagicMock()
        session.get.return_value.status_code = status_code
        with mock.patch.object(concord, "make_tracked_session", return_value=session):
            assert validate_credentials("key", "production") is expected

    def test_validate_credentials_swallows_exceptions(self):
        with mock.patch.object(concord, "make_tracked_session", side_effect=RuntimeError("boom")):
            assert validate_credentials("key", "production") is False


class TestSinglePagination:
    def test_single_request_selects_rows(self):
        rows, urls, _ = _run("groups", [{"groups": [{"id": 1}, {"id": 2}]}])
        assert [r["id"] for r in rows] == [1, 2]
        assert len(urls) == 1

    def test_tags_passes_organization_id_query_param(self):
        _rows, urls, _ = _run("tags", [{"tags": [{"id": 1}]}])
        assert "organizationId=42" in urls[0]

    def test_organizations_scoped_to_configured_org(self):
        # /user/me/organizations lists every accessible org; the synced table must not leak the
        # others when the source is configured for a specific org.
        payload = [{"organizations": [{"id": 42, "name": "mine"}, {"id": 7, "name": "someone else"}]}]
        rows, _urls, _ = _run("organizations", payload)
        assert [r["id"] for r in rows] == [42]

    def test_organizations_falls_back_to_first_org_when_unconfigured(self):
        payload = [{"organizations": [{"id": 7, "name": "first"}, {"id": 8, "name": "second"}]}]
        rows, _urls, _ = _run("organizations", payload, organization_id=None)
        assert [r["id"] for r in rows] == [7]


class TestPagePagination:
    def test_walks_pages_until_short_page(self, monkeypatch):
        monkeypatch.setattr(CONCORD_ENDPOINTS["agreements"], "page_size", 2)
        payloads = [
            {"items": [{"uuid": "a"}, {"uuid": "b"}]},
            {"items": [{"uuid": "c"}]},
        ]
        rows, urls, _ = _run("agreements", payloads, should_use_incremental_field=False)
        assert [r["uuid"] for r in rows] == ["a", "b", "c"]
        assert "page=0" in urls[0]
        assert "page=1" in urls[1]
        # agreements require the statuses filter on every request
        assert "statuses=DRAFT" in urls[0]

    def test_resumes_from_saved_page(self, monkeypatch):
        monkeypatch.setattr(CONCORD_ENDPOINTS["agreements"], "page_size", 2)
        manager = FakeManager(ConcordResumeConfig(page=7))
        _rows, urls, _ = _run("agreements", [{"items": [{"uuid": "x"}]}], manager=manager)
        assert "page=7" in urls[0]

    def test_incremental_adds_modified_at_filter(self, monkeypatch):
        monkeypatch.setattr(CONCORD_ENDPOINTS["agreements"], "page_size", 2)
        _rows, urls, _ = _run(
            "agreements",
            [{"items": [{"uuid": "a"}]}],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000000,
            incremental_field="modifiedAt",
        )
        assert "modifiedAt.from=1700000000000" in urls[0]


class TestIntraPageResume:
    """A byte-limit flush can fire mid-page. The checkpoint must record intra-page progress so a
    resume skips already-emitted rows instead of replaying the whole page forever (a DoS vector)."""

    def _iter(self, *, start_page=0, start_row_offset=0, manager=None, page_rows=None):
        config = CONCORD_ENDPOINTS["agreements"]
        manager = manager or FakeManager()
        # chunk_size=2 flushes every two rows; the 5-row page is shorter than page_size so the walk
        # stops after one page.
        batcher = Batcher(logger=mock.MagicMock(), chunk_size=2)
        rows = page_rows if page_rows is not None else [{"uuid": str(i)} for i in range(5)]
        with (
            mock.patch.object(config, "page_size", 100),
            mock.patch.object(concord, "_fetch", return_value={"items": rows}),
        ):
            tables = list(
                _iter_page(
                    session=mock.MagicMock(),
                    base_url="https://x",
                    path="/p",
                    headers={},
                    config=config,
                    logger=mock.MagicMock(),
                    batcher=batcher,
                    manager=manager,
                    base_params={},
                    start_page=start_page,
                    start_row_offset=start_row_offset,
                )
            )
        emitted = [r["uuid"] for table in tables for r in table.to_pylist()]
        return emitted, manager

    def test_mid_page_flush_advances_row_offset_monotonically(self):
        _emitted, manager = self._iter()
        # flushes after rows 1 and 3 (0-indexed) → committed counts 2 then 4, never rewinding to 0
        assert [(s.page, s.row_offset) for s in manager.saved] == [(0, 2), (0, 4)]

    def test_resume_skips_already_emitted_rows(self):
        emitted, _ = self._iter(start_row_offset=3)
        # rows 0–2 were committed last run; the resume must not re-emit them
        assert emitted == ["3", "4"]


class TestOffsetPagination:
    def test_members_use_start_offset_param(self, monkeypatch):
        monkeypatch.setattr(CONCORD_ENDPOINTS["members"], "page_size", 2)
        payloads = [
            {"members": [{"userOrganizationId": 1}, {"userOrganizationId": 2}]},
            {"members": [{"userOrganizationId": 3}]},
        ]
        rows, urls, _ = _run("members", payloads)
        assert [r["userOrganizationId"] for r in rows] == [1, 2, 3]
        assert "start=0" in urls[0]
        assert "start=2" in urls[1]

    def test_clauses_use_offset_param(self, monkeypatch):
        monkeypatch.setattr(CONCORD_ENDPOINTS["clauses"], "page_size", 2)
        rows, urls, _ = _run(
            "clauses",
            [{"organizationClauses": [{"id": 1}, {"id": 2}]}, {"organizationClauses": [{"id": 3}]}],
        )
        assert [r["id"] for r in rows] == [1, 2, 3]
        assert "offset=0" in urls[0]
        assert "offset=2" in urls[1]


class TestEventsWindowPagination:
    @freeze_time("2024-01-20")
    def test_walks_weekly_windows_with_bounded_range(self):
        last_value = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
        _rows, urls, manager = _run(
            "events",
            [{"events": [{"id": 1}]}],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )
        # 2024-01-01 .. 2024-01-20 chunked into <= 7-day windows
        assert "start=2024-01-01" in urls[0]
        assert "end=2024-01-08" in urls[0]
        assert len(urls) >= 3
        # windows advance and checkpoint so a crash resumes at the next window
        assert manager.saved and manager.saved[-1].window_start_ms is not None

    @freeze_time("2024-01-20")
    def test_resumes_from_saved_window(self):
        resume_ms = int(datetime(2024, 1, 15, tzinfo=UTC).timestamp() * 1000)
        manager = FakeManager(ConcordResumeConfig(window_start_ms=resume_ms))
        _rows, urls, _ = _run("events", [{"events": []}], manager=manager)
        assert "start=2024-01-15" in urls[0]

    def _iter_single_window(self, *, start_row_offset=0, manager=None):
        config = CONCORD_ENDPOINTS["events"]
        manager = manager or FakeManager()
        # A single window (start within 7 days of today) so the walk stops after one fetch; chunk_size=2
        # flushes every two rows so the mid-window checkpoint fires.
        batcher = Batcher(logger=mock.MagicMock(), chunk_size=2)
        start_ms = int(datetime(2024, 1, 18, tzinfo=UTC).timestamp() * 1000)
        rows = [{"id": i} for i in range(5)]
        with mock.patch.object(concord, "_fetch", return_value={"events": rows}):
            tables = list(
                _iter_events_windows(
                    session=mock.MagicMock(),
                    base_url="https://x",
                    path="/p",
                    headers={},
                    config=config,
                    logger=mock.MagicMock(),
                    batcher=batcher,
                    manager=manager,
                    start_ms=start_ms,
                    start_row_offset=start_row_offset,
                )
            )
        emitted = [r["id"] for table in tables for r in table.to_pylist()]
        return emitted, manager

    @freeze_time("2024-01-20")
    def test_mid_window_flush_advances_row_offset_monotonically(self):
        _emitted, manager = self._iter_single_window()
        window_ms = int(datetime(2024, 1, 18, tzinfo=UTC).timestamp() * 1000)
        # flushes after rows 1 and 3 (0-indexed) → committed counts 2 then 4, never rewinding to 0
        assert [(s.window_start_ms, s.row_offset) for s in manager.saved] == [(window_ms, 2), (window_ms, 4)]

    @freeze_time("2024-01-20")
    def test_resume_skips_already_emitted_window_rows(self):
        emitted, _ = self._iter_single_window(start_row_offset=3)
        # rows 0–2 were committed last run; the resume must not re-emit them
        assert emitted == [3, 4]


class TestConcordSource:
    @parameterized.expand(list(CONCORD_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        response = concord_source(
            api_key="key",
            environment="production",
            organization_id="42",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            manager=FakeManager(),
        )
        config = CONCORD_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
