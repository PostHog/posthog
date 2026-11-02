from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sequenzy import (
    SequenzySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.sequenzy import (
    SequenzyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sequenzy.source import SequenzySource


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _drive(
    endpoint: str,
    responses: list[ScriptedResponse],
    resume: SequenzyResumeConfig | None = None,
    company_id: str | None = None,
) -> DriveResult:
    driver = SourceDriver(SequenzySource(), SequenzySourceConfig(api_key="test-key", company_id=company_id))
    return driver.run(endpoint, responses, resume_state=resume)


class TestSequenzyPagination:
    def test_campaigns_offset_pagination_stops_at_total(self) -> None:
        responses = [
            _make_http_response(
                {
                    "success": True,
                    "campaigns": [{"id": f"camp_{i}"} for i in range(100)],
                    "pagination": {"limit": 100, "offset": 0, "count": 100, "total": 150, "hasMore": True},
                }
            ),
            _make_http_response(
                {
                    "success": True,
                    "campaigns": [{"id": f"camp_{i}"} for i in range(100, 150)],
                    "pagination": {"limit": 100, "offset": 100, "count": 50, "total": 150, "hasMore": False},
                }
            ),
        ]
        result = _drive("campaigns", responses)

        assert [(request.param("offset"), request.param("limit")) for request in result.requests] == [
            ("0", "100"),
            ("100", "100"),
        ]
        assert len(result.rows) == 150


class TestSequenzyResume:
    @pytest.mark.parametrize(
        ("endpoint", "resume", "param", "expected"),
        [
            ("subscribers", SequenzyResumeConfig(cursor="cur_saved"), "cursor", "cur_saved"),
            ("campaigns", SequenzyResumeConfig(offset=100), "offset", "100"),
            ("email_metrics", SequenzyResumeConfig(page=2), "page", "2"),
        ],
    )
    def test_resume_seeds_first_request(
        self, endpoint: str, resume: SequenzyResumeConfig, param: str, expected: Any
    ) -> None:
        selector = {"subscribers": "subscribers", "campaigns": "campaigns", "email_metrics": "emails"}[endpoint]
        responses = [
            _make_http_response({"success": True, selector: [], "pagination": {"nextCursor": None}}),
        ]
        result = _drive(endpoint, responses, resume)

        assert result.requests[0].param(param) == expected


class TestSequenzyCompanyHeader:
    def test_company_id_sets_workspace_header(self) -> None:
        responses = [
            _make_http_response({"success": True, "tags": []}),
        ]
        result = _drive("tags", responses, company_id="company_abc123")

        assert result.requests[0].headers["x-company-id"] == "company_abc123"


class TestValidateCredentials:
    def test_company_id_forwarded_as_header(self) -> None:
        with scripted_network(always(_make_http_response({}, status_code=200))) as network:
            validate_credentials("seq_user_key", company_id="company_abc123")

        assert network.requests_log[0].headers["x-company-id"] == "company_abc123"

    def test_non_ascii_key_returns_actionable_message_without_a_request(self) -> None:
        # A non-latin-1 key can't be encoded into the Authorization header; the raw
        # UnicodeEncodeError must never surface to the user.
        with scripted_network([]) as network:
            valid, message = validate_credentials("bad中key")

        assert valid is False
        assert "Retype it by hand" in (message or "")
        assert "latin-1" not in (message or "")
        assert network.requests_log == []
