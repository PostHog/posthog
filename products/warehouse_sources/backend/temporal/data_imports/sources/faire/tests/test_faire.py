import json
from typing import Any

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.faire.faire import (
    FairePaginator,
    FaireResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.faire.source import FaireSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.faire import FaireSourceConfig


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _driver() -> SourceDriver:
    return SourceDriver(FaireSource(), FaireSourceConfig(api_key="token"))


class TestFairePaginator:
    @parameterized.expand(
        [
            ("cursor_present", {"cursor": "next-page"}, True),
            ("cursor_absent", {"orders": []}, False),
            ("cursor_empty_string", {"cursor": ""}, False),
        ]
    )
    def test_update_state_reads_cursor(self, _name: str, body: dict[str, Any], expected_has_next: bool) -> None:
        paginator = FairePaginator(limit=50, filter_params=())

        paginator.update_state(_response(body))

        assert paginator.has_next_page is expected_has_next


class TestFaireSourceOrdersAndProducts:
    def test_paginates_until_cursor_disappears(self) -> None:
        result = _driver().run(
            "Orders",
            [
                ScriptedResponse(json={"orders": [{"id": "1"}, {"id": "2"}], "cursor": "page-2"}),
                ScriptedResponse(json={"orders": [{"id": "3"}]}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert len(result.requests) == 2
        assert result.paths[0] == "/external-api/v2/orders"
        assert result.requests[0].origin == "https://www.faire.com"
        assert result.params("cursor") == [None, "page-2"]
        assert result.params("limit") == ["50", "50"]

    def test_incremental_field_adds_updated_at_min(self) -> None:
        result = _driver().run(
            "Orders",
            [ScriptedResponse(json={"orders": [{"id": "1"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert result.requests[0].param("updated_at_min") == "2026-01-01T00:00:00Z"

    def test_sync_client_does_not_follow_redirects(self) -> None:
        # The token rides in a custom header requests preserves across cross-origin redirects, so
        # the sync client must pin allow_redirects off.
        result = _driver().run(
            "Orders",
            [
                ScriptedResponse(
                    status=302,
                    json={"orders": []},
                    headers={"Location": "https://example.com/redirected"},
                )
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert "refusing to follow" in str(result.raised)
        assert result.paths == ["/external-api/v2/orders"]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "Orders",
            [ScriptedResponse(json={"orders": [{"id": "2"}]})],
            resume_state=FaireResumeConfig(cursor="page-2"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["2"]
        assert len(result.requests) == 1
        assert result.queries[0] == {"cursor": ("page-2",), "limit": ("50",)}


class TestFaireSourceBrand:
    def test_never_saves_resume_state(self) -> None:
        result = _driver().run("Brand", [ScriptedResponse(json={"brand_id": "b1"})])

        assert result.raised is None
        assert result.rows == [{"brand_id": "b1"}]
        assert result.saved_states == []


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("token") == (True, 200)

        assert [request.path for request in network.requests_log] == ["/external-api/v2/brands/profile"]
        assert network.requests_log[0].headers["x-faire-access-token"] == "token"
