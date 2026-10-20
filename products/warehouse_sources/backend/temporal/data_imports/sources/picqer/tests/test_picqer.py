from datetime import date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.picqer import PicqerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.picqer import (
    PicqerResumeConfig,
    _build_params,
    normalize_account,
    to_picqer_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.settings import PAGE_SIZE, PICQER_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.source import PicqerSource


class TestNormalizeAccount:
    @pytest.mark.parametrize(
        "value",
        [
            "acme/../evil",
            "acme.evil.com",
            "acme@evil.com",
            "",
            "ac me",
            "acme-",
        ],
    )
    def test_invalid_accounts_raise(self, value: str) -> None:
        # The account is the host the stored API key is sent to; a loosened regex would let an org
        # member retarget the credential at a server they control.
        with pytest.raises(ValueError):
            normalize_account(value)


class TestToPicqerDatetime:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2020, 1, 2, 3, 4, 5), "2020-01-02 03:04:05"),
            (date(2020, 1, 2), "2020-01-02 00:00:00"),
            ("2020-01-02T03:04:05", "2020-01-02 03:04:05"),
            ("2020-01-02 03:04:05", "2020-01-02 03:04:05"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        # Picqer's `updated_after` filter expects `YYYY-MM-DD HH:MM:SS`; a broken format silently
        # returns wrong/empty incremental pages.
        assert to_picqer_datetime(value) == expected


class TestBuildParams:
    def test_full_refresh_endpoint_never_filters(self) -> None:
        # orders exposes only a creation-date filter (`sincedate`), so it syncs full refresh; a
        # cursor must never leak into the request and silently drop updated rows.
        params = _build_params(
            PICQER_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
        )
        assert params == {}


def _page(n: int) -> ScriptedResponse:
    # Picqer list endpoints return a bare JSON array (no envelope).
    return ScriptedResponse(json=[{"idorder": i} for i in range(n)])


def _driver() -> SourceDriver:
    return SourceDriver(PicqerSource(), PicqerSourceConfig(account_name="acme", api_key="key"))


class TestPagination:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("orders", [_page(2)], resume_state=PicqerResumeConfig(offset=PAGE_SIZE))

        assert result.raised is None
        assert len(result.rows) == 2
        assert result.params("offset") == [str(PAGE_SIZE)]

    def test_incremental_filter_present_on_every_page(self) -> None:
        result = _driver().run(
            "purchaseorders",
            [_page(PAGE_SIZE), _page(1)],
            incremental_field="updated",
            db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
        )

        # The filter must stay on every paginated request so pagination walks only the filtered set.
        assert result.raised is None
        assert result.params("updated_after") == ["2020-01-02 03:04:05"] * 2
        assert result.params("offset") == ["0", str(PAGE_SIZE)]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status,expected_ok",
        [
            (200, True),
            # 403 = valid key, insufficient scope — accepted at source-create (per-table scope
            # reported separately).
            (403, True),
            (401, False),
            (500, False),
        ],
    )
    def test_status_mapping(self, status: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            ok, code = validate_credentials("acme", "key")

        assert ok is expected_ok
        assert code == status
        assert {request.path for request in network.requests_log} == {"/api/v1/warehouses"}

    def test_bad_account_raises_before_probe(self) -> None:
        # A malformed account must fail loud (so the caller can surface a precise message) rather
        # than being swallowed as an unreachable probe.
        with pytest.raises(ValueError):
            validate_credentials("acme.evil.com", "key")
