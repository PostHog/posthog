from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.concord import concord as concord_module
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.concord import (
    ConcordResumeConfig,
    _agreement_incremental_params,
    _flatten_folder_tree,
    _member_id,
    _to_epoch_ms,
    base_url_for_environment,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.settings import CONCORD_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.source import ConcordSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.concord import (
    ConcordSourceConfig,
)


def _driver(organization_id: str | None = "42") -> SourceDriver:
    return SourceDriver(ConcordSource(), ConcordSourceConfig(api_key="key", organization_id=organization_id))


@pytest.fixture
def flush_every_two_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    def small_batcher(logger: Any, chunk_size: int, chunk_size_bytes: int) -> Batcher:
        return Batcher(logger=logger, chunk_size=2)

    monkeypatch.setattr(concord_module, "Batcher", small_batcher)


def _rows(result: DriveResult) -> list[dict[str, Any]]:
    return [row for table in result.items for row in table.to_pylist()]


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
    def test_resolves_first_org_when_blank(self):
        result = _driver(None).run(
            "tags",
            [ScriptedResponse(json={"organizations": [{"id": 99}, {"id": 100}]}), ScriptedResponse(json={"tags": []})],
        )
        assert result.raised is None
        assert result.requests[1].param("organizationId") == "99"

    def test_raises_when_no_org_accessible(self):
        result = _driver("").run("tags", [ScriptedResponse(json={"organizations": []})])
        assert isinstance(result.raised, ValueError)
        assert "No Concord organizations" in str(result.raised)


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_validate_credentials_status_mapping(self, _name, status_code, expected):
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key", "production") is expected
        assert network.requests_log[0].path == "/api/rest/1/user/me/organizations"
        assert network.requests_log[0].headers["x-api-key"] == "key"
        assert network.session_options[0]["redact_values"] == ("key",)

    def test_validate_credentials_swallows_exceptions(self):
        with scripted_network([ConnectionResetError("reset")]) as network:
            assert validate_credentials("key", "production") is False
        assert network.requests_log[0].path == "/api/rest/1/user/me/organizations"


class TestSinglePagination:
    def test_tags_passes_organization_id_query_param(self):
        result = _driver().run("tags", [ScriptedResponse(json={"tags": [{"id": 1}]})])
        assert result.raised is None
        assert result.requests[0].param("organizationId") == "42"

    def test_organizations_scoped_to_configured_org(self):
        # /user/me/organizations lists every accessible org; the synced table must not leak the
        # others when the source is configured for a specific org.
        payload = {"organizations": [{"id": 42, "name": "mine"}, {"id": 7, "name": "someone else"}]}
        result = _driver().run("organizations", [ScriptedResponse(json=payload)])
        assert result.raised is None
        assert [r["id"] for r in _rows(result)] == [42]

    def test_organizations_falls_back_to_first_org_when_unconfigured(self):
        payload = {"organizations": [{"id": 7, "name": "first"}, {"id": 8, "name": "second"}]}
        result = _driver(None).run("organizations", [ScriptedResponse(json=payload)])
        assert result.raised is None
        assert [r["id"] for r in _rows(result)] == [7]


class TestPagePagination:
    def test_walks_pages_until_short_page(self, monkeypatch):
        monkeypatch.setattr(CONCORD_ENDPOINTS["agreements"], "page_size", 2)
        payloads = [
            {"items": [{"uuid": "a"}, {"uuid": "b"}]},
            {"items": [{"uuid": "c"}]},
        ]
        result = _driver().run("agreements", [ScriptedResponse(json=payload) for payload in payloads])
        assert result.raised is None
        assert [r["uuid"] for r in _rows(result)] == ["a", "b", "c"]
        assert result.params("page") == ["0", "1"]
        # agreements require the statuses filter on every request
        assert all("DRAFT" in request.query["statuses"] for request in result.requests)

    def test_incremental_adds_modified_at_filter(self, monkeypatch):
        monkeypatch.setattr(CONCORD_ENDPOINTS["agreements"], "page_size", 2)
        result = _driver().run(
            "agreements",
            [ScriptedResponse(json={"items": [{"uuid": "a"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000000,
            incremental_field="modifiedAt",
        )
        assert result.raised is None
        assert result.requests[0].param("modifiedAt.from") == "1700000000000"


class TestIntraPageResume:
    """A byte-limit flush can fire mid-page. The checkpoint must record intra-page progress so a
    resume skips already-emitted rows instead of replaying the whole page forever (a DoS vector)."""

    @pytest.mark.usefixtures("flush_every_two_rows")
    def test_resume_skips_already_emitted_rows(self):
        result = _driver().run(
            "agreements",
            [ScriptedResponse(json={"items": [{"uuid": str(i)} for i in range(5)]})],
            resume_state=ConcordResumeConfig(page=0, row_offset=3),
        )
        # rows 0–2 were committed last run; the resume must not re-emit them
        assert result.raised is None
        assert result.params("page") == ["0"]
        assert [r["uuid"] for r in _rows(result)] == ["3", "4"]
        assert result.saved_states == [ConcordResumeConfig(page=0, row_offset=5)]

    @pytest.mark.usefixtures("flush_every_two_rows")
    def test_mid_page_flush_checkpoints_the_row_offset(self):
        result = _driver().run("agreements", [ScriptedResponse(json={"items": [{"uuid": str(i)} for i in range(5)]})])
        assert result.raised is None
        assert result.saved_states == [
            ConcordResumeConfig(page=0, row_offset=2),
            ConcordResumeConfig(page=0, row_offset=4),
        ]


class TestOffsetPagination:
    def test_clauses_use_offset_param(self, monkeypatch):
        monkeypatch.setattr(CONCORD_ENDPOINTS["clauses"], "page_size", 2)
        result = _driver().run(
            "clauses",
            [
                ScriptedResponse(json={"organizationClauses": [{"id": 1}, {"id": 2}]}),
                ScriptedResponse(json={"organizationClauses": [{"id": 3}]}),
            ],
        )
        assert result.raised is None
        assert [r["id"] for r in _rows(result)] == [1, 2, 3]
        assert result.params("offset") == ["0", "2"]


class TestEventsWindowPagination:
    @time_machine.travel("2024-01-20", tick=False)
    def test_walks_weekly_windows_with_bounded_range(self):
        last_value = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
        result = _driver().run(
            "events",
            [ScriptedResponse(json={"events": []}) for _ in range(3)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )
        # 2024-01-01 .. 2024-01-20 chunked into <= 7-day windows
        assert result.raised is None
        assert result.params("start") == ["2024-01-01", "2024-01-08", "2024-01-15"]
        assert result.params("end") == ["2024-01-08", "2024-01-15", "2024-01-20"]
        # windows advance and checkpoint so a crash resumes at the next window
        assert [state.window_start_ms for state in result.saved_states] == [
            int(datetime(2024, 1, day, tzinfo=UTC).timestamp() * 1000) for day in (8, 15)
        ]

    @time_machine.travel("2024-01-20", tick=False)
    def test_resumes_from_saved_window(self):
        resume_ms = int(datetime(2024, 1, 15, tzinfo=UTC).timestamp() * 1000)
        result = _driver().run(
            "events",
            [ScriptedResponse(json={"events": []})],
            resume_state=ConcordResumeConfig(window_start_ms=resume_ms),
        )
        assert result.raised is None
        assert result.requests[0].param("start") == "2024-01-15"

    @pytest.mark.usefixtures("flush_every_two_rows")
    @time_machine.travel("2024-01-20", tick=False)
    def test_resume_skips_already_emitted_window_rows(self):
        start_ms = int(datetime(2024, 1, 18, tzinfo=UTC).timestamp() * 1000)
        result = _driver().run(
            "events",
            [ScriptedResponse(json={"events": [{"id": i} for i in range(5)]})],
            resume_state=ConcordResumeConfig(window_start_ms=start_ms, row_offset=3),
        )
        # rows 0–2 were committed last run; the resume must not re-emit them
        assert result.raised is None
        assert [r["id"] for r in _rows(result)] == [3, 4]
        assert result.saved_states == [ConcordResumeConfig(window_start_ms=start_ms, row_offset=5)]

    @pytest.mark.usefixtures("flush_every_two_rows")
    @time_machine.travel("2024-01-20", tick=False)
    def test_mid_window_flush_checkpoints_the_row_offset(self):
        start_ms = int(datetime(2024, 1, 18, tzinfo=UTC).timestamp() * 1000)
        result = _driver().run(
            "events",
            [ScriptedResponse(json={"events": [{"id": i} for i in range(5)]})],
            resume_state=ConcordResumeConfig(window_start_ms=start_ms),
        )
        assert result.raised is None
        assert [state.row_offset for state in result.saved_states] == [2, 4]


class TestMemberId:
    @parameterized.expand(
        [
            ("active_user", {"status": "ACTIVE", "user": {"id": 7}}, 7),
            ("invitation", {"status": "INVITED", "invitation": {"id": 3}}, 3),
            # An invitation can carry the invitee's user account too; the invitation id still wins so
            # every INVITED row is keyed on the same id space.
            ("invitation_with_user", {"status": "INVITED", "user": {"id": 7}, "invitation": {"id": 3}}, 3),
            ("neither", {"status": "ACTIVE"}, None),
        ]
    )
    def test_member_id(self, _name, row, expected):
        assert _member_id(row) == expected


class TestAgreementFanout:
    def _run(
        self,
        endpoint: str,
        *,
        agreements: list[dict[str, Any]],
        child: Any,
        resume_state: ConcordResumeConfig | None = None,
    ) -> DriveResult:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/agreements"):
                return ScriptedResponse(json={"items": agreements})
            return ScriptedResponse(json=child)

        return _driver().run(endpoint, answer, resume_state=resume_state)

    def test_fetches_each_agreement_and_injects_the_parent_uid(self):
        result = self._run(
            "agreement_fields",
            agreements=[{"uuid": "A"}, {"uuid": "B"}],
            child={"fields": [{"id": 1, "name": "price", "value": "10"}]},
        )
        assert result.raised is None
        assert [(r["agreement_uuid"], r["id"]) for r in _rows(result)] == [("A", 1), ("B", 1)]
        assert any("/agreements/A/summary/fields" in path for path in result.paths)
        assert any("/agreements/B/summary/fields" in path for path in result.paths)

    def test_members_keep_user_and_invitation_ids_apart(self):
        result = self._run(
            "agreement_members",
            agreements=[{"uuid": "A"}],
            child=[
                {"status": "ACTIVE", "user": {"id": 7, "email": "a@example.com"}},
                {"status": "INVITED", "invitation": {"id": 7, "email": "b@example.com"}},
            ],
        )
        # The same numeric id in two id spaces must stay two rows, or merge would collapse them.
        assert result.raised is None
        assert [(r["status"], r["member_id"]) for r in _rows(result)] == [("ACTIVE", 7), ("INVITED", 7)]

    @parameterized.expand(
        [
            ("approval", "agreement_approval", {"status": "PENDING", "blockThirdPartySignature": True}),
            ("signature", "agreement_signature", {"enforceOrder": True, "signatureProvider": "CONCORD"}),
            ("metadata", "agreement_metadata", {"title": "NDA", "status": "DRAFT"}),
        ]
    )
    def test_single_object_child_becomes_one_row_per_agreement(self, _name, endpoint, child):
        result = self._run(endpoint, agreements=[{"uuid": "A"}, {"uuid": "B"}], child=child)
        assert result.raised is None
        rows = _rows(result)
        assert [r["agreement_uuid"] for r in rows] == ["A", "B"]
        # the object's own fields land on the row alongside the parent uid
        assert set(child) <= set(rows[0])

    @parameterized.expand([("approval", "agreement_approval"), ("signature", "agreement_signature")])
    def test_single_object_child_skips_an_agreement_with_nothing_configured(self, _name, endpoint):
        result = self._run(endpoint, agreements=[{"uuid": "A"}], child={})
        # an empty body would otherwise seed a row carrying nothing but the parent uid
        assert result.raised is None
        assert _rows(result) == []

    @parameterized.expand([("forbidden", 403), ("not_found", 404)])
    def test_skips_an_agreement_the_key_cannot_read(self, _name, status_code):
        result = _driver().run(
            "agreement_fields",
            [
                ScriptedResponse(json={"items": [{"uuid": "A"}, {"uuid": "B"}]}),
                ScriptedResponse(status=status_code),
                ScriptedResponse(json={"fields": [{"id": 1}]}),
            ],
        )
        assert result.raised is None
        assert [r["agreement_uuid"] for r in _rows(result)] == ["B"]

    def test_other_child_errors_fail_the_sync(self):
        result = _driver().run(
            "agreement_fields",
            [ScriptedResponse(json={"items": [{"uuid": "A"}]}), ScriptedResponse(status=400)],
        )
        assert isinstance(result.raised, requests.HTTPError)

    def test_resumes_from_the_saved_parent_position(self):
        result = self._run(
            "agreement_fields",
            agreements=[{"uuid": "A"}, {"uuid": "B"}],
            child={"fields": [{"id": 1}]},
            resume_state=ConcordResumeConfig(parent_page=3, parent_index=1),
        )
        assert result.raised is None
        assert result.requests[0].param("page") == "3"
        # agreement A finished last run, so only B is fetched again
        assert [r["agreement_uuid"] for r in _rows(result)] == ["B"]
        assert all("/agreements/A/" not in path for path in result.paths)

    def test_mid_agreement_flush_checkpoints_the_agreement_still_in_flight(self):
        # The source flushes every 2,000 rows, so each agreement crosses a flush boundary.
        result = self._run(
            "agreement_fields",
            agreements=[{"uuid": "A"}, {"uuid": "B"}],
            child={"fields": [{"id": i} for i in range(2001)]},
        )
        # A's last row is still buffered at the first flush, so a resume must redo A.
        assert result.raised is None
        assert [(s.parent_page, s.parent_index) for s in result.saved_states] == [(0, 0), (0, 1)]


class TestConcordSource:
    @parameterized.expand(list(CONCORD_ENDPOINTS.keys()))
    @time_machine.travel("2024-01-20", tick=False)
    def test_source_response_shape(self, endpoint):
        config = CONCORD_ENDPOINTS[endpoint]

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/agreements"):
                return ScriptedResponse(json={"items": []})
            if config.data_selector is None:
                return ScriptedResponse(json=[])
            return ScriptedResponse(json={config.data_selector: []})

        result = _driver().run(
            endpoint,
            answer,
            resume_state=ConcordResumeConfig(window_start_ms=1705708800000),
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
