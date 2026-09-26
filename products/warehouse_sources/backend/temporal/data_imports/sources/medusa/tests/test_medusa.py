import json
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.medusa.medusa import (
    MedusaPaginator,
    MedusaResumeConfig,
    _read_capped,
    _to_iso8601,
    get_resource,
    medusa_source,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.medusa.settings import (
    MAX_ROWS_PER_SYNC,
    MEDUSA_ENDPOINTS,
    PAGE_SIZE,
)

MEDUSA_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.medusa.medusa"

BASE_URL = "https://store.example.com"


def _json_response(body: dict[str, Any], status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


def _streamed_response(chunks: list[bytes]) -> Response:
    response = Response()
    response.status_code = 200
    raw = MagicMock()
    raw.stream.return_value = iter(chunks)
    response.raw = raw
    return response


def _make_manager(resume_state: MedusaResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestMedusaTransport:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("store.example.com", "https://store.example.com"),
            ("https://store.example.com/", "https://store.example.com"),
            ("https://store.example.com:9000", "https://store.example.com:9000"),
            ("https://proxy.example.com/medusa", "https://proxy.example.com/medusa"),
        ],
    )
    def test_normalizes_valid_urls(self, raw: str, expected: str) -> None:
        assert normalize_base_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "http://store.example.com",  # plaintext would put the API key on the wire in the clear
            "https://user:pass@store.example.com",  # credentials in the authority
            "https://evil.com\\@store.example.com",  # urlparse/http-client host disagreement
            "https://evil.com%40store.example.com",  # encoded authority delimiter
            "https://",
        ],
    )
    def test_rejects_unsafe_urls(self, raw: str | None) -> None:
        with pytest.raises(ValueError):
            normalize_base_url(raw)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            ("2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05Z"),
            ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
            ("2026-01-02 03:04:05", "2026-01-02T03:04:05Z"),
            ("not a date", None),
        ],
    )
    def test_to_iso8601(self, value: Any, expected: str | None) -> None:
        assert _to_iso8601(value) == expected

    def test_incremental_resource_filters_and_sorts_on_the_cursor(self) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(MEDUSA_ENDPOINTS["Orders"], should_use_incremental_field=True),
        )

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        endpoint = resource["endpoint"]
        assert endpoint["path"] == "/admin/orders"
        assert endpoint["params"]["order"] == "updated_at"
        assert endpoint["incremental"]["start_param"] == "updated_at[$gte]"
        assert endpoint["incremental"]["cursor_path"] == "updated_at"

    def test_full_refresh_resource_omits_the_watermark_filter(self) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(MEDUSA_ENDPOINTS["Orders"], should_use_incremental_field=False),
        )

        assert resource["write_disposition"] == "replace"
        endpoint = resource["endpoint"]
        assert "incremental" not in endpoint
        assert endpoint["params"]["order"] == "created_at"
        assert not any("$gte" in param for param in endpoint["params"])

    def test_incremental_rejected_for_endpoint_without_timestamp_filters(self) -> None:
        with pytest.raises(ValueError, match="does not support incremental"):
            get_resource(MEDUSA_ENDPOINTS["PriceLists"], should_use_incremental_field=True)

    def test_incremental_rejected_for_unadvertised_cursor_field(self) -> None:
        with pytest.raises(ValueError, match="no incremental field 'created_at'"):
            get_resource(
                MEDUSA_ENDPOINTS["Orders"],
                should_use_incremental_field=True,
                incremental_field_name="created_at",
            )

    def test_paginator_aborts_past_the_row_budget_even_after_a_resume(self) -> None:
        # A user-controlled host that keeps returning full pages forever must fail the sync
        # loudly instead of holding the import until its activity timeout. The budget rides
        # `offset`, so a resumed sync keeps the position it already paid for.
        paginator = MedusaPaginator()
        paginator.set_resume_state({"offset": MAX_ROWS_PER_SYNC})
        rows = [{"id": f"order_{i}"} for i in range(PAGE_SIZE)]

        with pytest.raises(ValueError, match="did not terminate"):
            paginator.update_state(_json_response({"orders": rows}), data=rows)

    def test_read_capped_aborts_over_the_byte_limit(self) -> None:
        # A hostile host can return an arbitrarily large or highly compressed body; the cap
        # aborts mid-stream instead of buffering it all into worker memory.
        with patch(f"{MEDUSA_MODULE}.MAX_RESPONSE_BYTES", 3):
            with pytest.raises(ValueError, match="exceeded"):
                _read_capped(_streamed_response([b"ab", b"cd"]))

    def test_validate_credentials_probes_with_basic_key_auth(self) -> None:
        with patch(f"{MEDUSA_MODULE}._bounded_session") as mock_session:
            mock_session.return_value.get.return_value = MagicMock(status_code=200)

            result = validate_credentials(BASE_URL, "sk_test")

        assert result == (True, 200)
        call = mock_session.return_value.get.call_args
        assert call.args[0] == f"{BASE_URL}/admin/regions?limit=1"
        # The key is the Basic username with an empty password.
        assert call.kwargs["auth"] == HTTPBasicAuth("sk_test", "")
        assert call.kwargs["allow_redirects"] is False

    @patch(f"{MEDUSA_MODULE}.rest_api_resource")
    def test_source_pins_requests_to_the_configured_host(self, mock_rest_api_resource: MagicMock) -> None:
        medusa_source(
            base_url=BASE_URL,
            api_key="sk_test",
            endpoint="Orders",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        config = mock_rest_api_resource.call_args.args[0]
        client = config["client"]
        assert client["base_url"] == BASE_URL
        assert client["auth"] == {"type": "http_basic", "username": "sk_test", "password": ""}
        assert client["allowed_hosts"] == []
        assert client["allow_redirects"] is False

    @patch(f"{MEDUSA_MODULE}.rest_api_resource")
    def test_source_response_partitions_on_a_stable_field(self, mock_rest_api_resource: MagicMock) -> None:
        response = medusa_source(
            base_url=BASE_URL,
            api_key="sk_test",
            endpoint="Orders",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert response.name == "Orders"
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"
        mock_rest_api_resource.assert_called_once()

    @patch(f"{MEDUSA_MODULE}.rest_api_resource")
    def test_fresh_run_starts_without_paginator_state(self, mock_rest_api_resource: MagicMock) -> None:
        medusa_source(
            base_url=BASE_URL,
            api_key="sk_test",
            endpoint="Orders",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] is None

    @patch(f"{MEDUSA_MODULE}.rest_api_resource")
    def test_resume_seeds_the_saved_paginator_state(self, mock_rest_api_resource: MagicMock) -> None:
        medusa_source(
            base_url=BASE_URL,
            api_key="sk_test",
            endpoint="Orders",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(MedusaResumeConfig(paginator_state={"offset": 300})),
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"offset": 300}

    @patch(f"{MEDUSA_MODULE}.rest_api_resource")
    def test_checkpoint_saves_only_resumable_state(self, mock_rest_api_resource: MagicMock) -> None:
        manager = _make_manager()
        medusa_source(
            base_url=BASE_URL,
            api_key="sk_test",
            endpoint="Orders",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )
        save_checkpoint = mock_rest_api_resource.call_args.kwargs["resume_hook"]

        save_checkpoint({"offset": 200})
        manager.save_state.assert_called_once_with(MedusaResumeConfig(paginator_state={"offset": 200}))

        manager.save_state.reset_mock()
        save_checkpoint(None)
        manager.save_state.assert_not_called()
