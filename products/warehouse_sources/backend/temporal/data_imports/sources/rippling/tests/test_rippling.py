from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rippling import (
    RipplingSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling import (
    PAGE_SIZE,
    RipplingResumeConfig,
    _absolutize_next_url,
    _build_params,
    _format_filter_timestamp,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.source import RipplingSource


def _response(items: list[dict[str, Any]], next_link: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"results": items, "next_link": next_link})


def _driver() -> SourceDriver:
    return SourceDriver(RipplingSource(), RipplingSourceConfig(api_token="token"))


class TestFormatFilterTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 10, 1, 3, 4, 5, tzinfo=UTC), "2024-10-01T03:04:05"),
            (datetime(2024, 10, 1, 3, 4, 5), "2024-10-01T03:04:05"),
            (date(2024, 10, 1), "2024-10-01T00:00:00"),
            ("2024-10-01T00:00:00", "2024-10-01T00:00:00"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_filter_timestamp(value) == expected


class TestBuildParams:
    def test_incremental_builds_odata_filter_and_sort(self):
        params = _build_params(
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 10, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert params["filter"] == "updated_at ge 2024-10-01T00:00:00"
        assert params["order_by"] == "updated_at"
        assert params["limit"] == PAGE_SIZE


class TestAbsolutizeNextUrl:
    @pytest.mark.parametrize(
        "next_link",
        [
            "https://attacker.example/workers",
            "//attacker.example/workers",
            "http://rest.ripplingapis.com/workers",
            "https://rest.ripplingapis.com.attacker.example/workers",
        ],
    )
    def test_rejects_off_domain_links(self, next_link):
        with pytest.raises(ValueError):
            _absolutize_next_url(next_link)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # A valid token without the companies.read scope still 403s; only 401
            # means the token itself is bad.
            (403, True),
            (401, False),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, expected):
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            assert validate_credentials("token") is expected


class TestGetRows:
    def test_absolute_next_link_used_as_is(self):
        absolute = "https://rest.ripplingapis.com/workers?cursor=xyz"

        result = _driver().run("workers", [_response([{"id": "1"}], next_link=absolute), _response([])])

        assert result.urls[1] == absolute

    def test_resumes_from_saved_state(self):
        resume_url = "https://rest.ripplingapis.com/workers?cursor=resume"

        result = _driver().run(
            "workers", [_response([{"id": "9"}])], resume_state=RipplingResumeConfig(next_url=resume_url)
        )

        assert result.urls[0] == resume_url

    def test_off_domain_next_link_raises(self):
        result = _driver().run("workers", [_response([{"id": "1"}], next_link="https://attacker.example/workers")])

        assert isinstance(result.raised, ValueError)
        assert "off-domain" in str(result.raised)
