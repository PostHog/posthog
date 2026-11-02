from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.productboard import (
    ProductboardSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard import (
    ProductboardResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.source import ProductboardSource

NOTES_URL = "https://api.productboard.com/v2/notes"


def _driver() -> SourceDriver:
    return SourceDriver(ProductboardSource(), ProductboardSourceConfig(access_token="token"))


def _page(body: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json=body)


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2023, 10, 1, 10, 0, 0, tzinfo=UTC), "2023-10-01T10:00:00Z"),
            (datetime(2023, 10, 1, 10, 0, 0), "2023-10-01T10:00:00Z"),
            (date(2023, 10, 1), "2023-10-01T00:00:00Z"),
            ("2023-10-01T10:00:00Z", "2023-10-01T10:00:00Z"),
            (123, "123"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_entity_endpoint_adds_type_filter(self):
        assert _build_initial_params("features", False, None, None) == {"type[]": "feature"}


class TestValidateCredentials:
    def test_probe_sends_the_bearer_token_and_redacts_it(self):
        with scripted_network([ScriptedResponse(status=200, json={"data": []})]) as network:
            assert validate_credentials("token", "/notes") == (True, 200)

        assert network.requests_log[0].url == NOTES_URL
        assert network.requests_log[0].headers["authorization"] == "Bearer token"
        assert network.session_options[0]["redact_values"] == ("token",)


class TestPagination:
    def test_resumes_from_saved_state(self):
        resume_url = f"{NOTES_URL}?pageCursor=resume"

        result = _driver().run(
            "notes",
            [_page({"data": [{"id": "9"}], "links": {}})],
            resume_state=ProductboardResumeConfig(next_url=resume_url),
        )

        assert [r["id"] for r in result.rows] == ["9"]
        # The seeded next_url drives the very first request, with no leftover base params.
        assert result.urls[0] == resume_url
        assert result.queries[0] == {"pageCursor": ("resume",)}

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self):
        result = _driver().run("notes", [_page({"data": [{"id": "1"}], "links": {}})])

        assert result.urls == [NOTES_URL]

    def test_checkpoints_next_url_after_each_page(self):
        # Save state points at the page still to fetch (links.next), saved after the current page is
        # yielded; the final page (no next link) records no checkpoint.
        page2_url = f"{NOTES_URL}?pageCursor=c2"

        result = _driver().run(
            "notes",
            [
                _page({"data": [{"id": "1"}], "links": {"next": page2_url}}),
                _page({"data": [{"id": "2"}], "links": {}}),
            ],
        )

        assert result.saved_states == [ProductboardResumeConfig(next_url=page2_url)]
        assert result.urls[1] == page2_url

    def test_notes_incremental_sends_server_filter(self):
        result = _driver().run(
            "notes",
            [_page({"data": [{"id": "n1"}], "links": {}})],
            incremental_field="updatedAt",
            db_incremental_field_last_value=datetime(2023, 10, 1, 10, 0, 0, tzinfo=UTC),
        )

        assert result.queries[0] == {"updatedFrom": ("2023-10-01T10:00:00Z",)}


class TestRelationshipFanout:
    def test_entity_relationships_walk_every_entity_and_child_page(self):
        child_page2_url = "https://api.productboard.com/v2/entities/e1/relationships?pageCursor=c2"

        result = _driver().run(
            "entity_relationships",
            [
                _page({"data": [{"id": "e1", "type": "feature"}, {"id": "e2", "type": "component"}], "links": {}}),
                _page(
                    {
                        "data": [{"type": "parent", "target": {"id": "e2", "type": "component", "links": {}}}],
                        "links": {"next": child_page2_url},
                    }
                ),
                _page({"data": [{"type": "link", "target": {"id": "o1", "type": "objective"}}], "links": {}}),
                _page({"data": [{"type": "child", "target": {"id": "e1", "type": "feature"}}], "links": {}}),
            ],
        )

        assert result.raised is None
        assert result.urls == [
            "https://api.productboard.com/v2/entities",
            "https://api.productboard.com/v2/entities/e1/relationships",
            child_page2_url,
            "https://api.productboard.com/v2/entities/e2/relationships",
        ]
        assert [
            (row["entity_id"], row["entity_type"], row["type"], row["target_id"], row["target_type"])
            for row in result.rows
        ] == [
            ("e1", "feature", "parent", "e2", "component"),
            ("e1", "feature", "link", "o1", "objective"),
            ("e2", "component", "child", "e1", "feature"),
        ]
        assert all("target" not in row for row in result.rows)
        # The checkpoint tracks the parent page, so it does not keep every finished entity.
        assert result.saved_states and all("parent" in (state.fanout_state or {}) for state in result.saved_states)

    def test_note_relationships_skip_a_note_deleted_after_listing(self):
        result = _driver().run(
            "note_relationships",
            [
                _page({"data": [{"id": "n1"}, {"id": "n2"}], "links": {}}),
                ScriptedResponse(status=404, json={"errors": [{"code": "not_found"}]}),
                _page({"data": [{"type": "customer", "target": {"id": "c1", "type": "company"}}], "links": {}}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v2/notes", "/v2/notes/n1/relationships", "/v2/notes/n2/relationships"]
        assert [(row["note_id"], row["type"], row["target_id"]) for row in result.rows] == [("n2", "customer", "c1")]
