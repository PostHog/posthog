import json
from collections.abc import Iterable
from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.lightfield import (
    check_token,
    lightfield_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.settings import (
    LIGHTFIELD_ENDPOINTS,
    LIGHTFIELD_PAGE_SIZE,
)


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _record(record_id: str) -> dict[str, Any]:
    return {
        "id": record_id,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "fields": {"$name": {"value": f"Record {record_id}", "valueType": "TEXT"}},
        "relationships": {},
        "httpLink": f"https://app.lightfield.app/accounts/{record_id}",
    }


def _page(record_ids: list[str], total_count: int) -> dict[str, Any]:
    return {
        "data": [_record(record_id) for record_id in record_ids],
        "object": "list",
        "totalCount": total_count,
    }


class TestLightfieldSourcePagination:
    def _drive(self, responses: list[Response]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
        """Drive ``lightfield_source`` with a mocked HTTP session. Returns the params sent
        with each request (shallow copies — the paginator mutates the Request in place
        between pages), the rows yielded, and the session headers the client installed."""
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = lightfield_source(
                api_key="sk_lf_test",
                endpoint="accounts",
                team_id=123,
                job_id="test_job",
                api_version="2026-03-01",
            )
            rows = [row for page in cast(Iterable[Any], source_response.items()) for row in page]
            return sent_params, rows, dict(mock_session.headers)

    def test_paginates_with_offset_until_short_page(self) -> None:
        first_page_ids = [f"acc_{i}" for i in range(LIGHTFIELD_PAGE_SIZE)]
        responses = [
            _make_http_response(_page(first_page_ids, total_count=30)),
            _make_http_response(_page(["acc_25", "acc_26"], total_count=30)),
        ]

        sent_params, rows, _ = self._drive(responses)

        assert [p.get("offset") for p in sent_params] == [0, LIGHTFIELD_PAGE_SIZE]
        assert all(p.get("limit") == LIGHTFIELD_PAGE_SIZE for p in sent_params)
        assert len(rows) == LIGHTFIELD_PAGE_SIZE + 2

    def test_stops_at_total_count_without_extra_request(self) -> None:
        # A full page whose totalCount equals the rows returned must not pay for a
        # trailing empty-page request.
        page_ids = [f"acc_{i}" for i in range(LIGHTFIELD_PAGE_SIZE)]
        responses = [_make_http_response(_page(page_ids, total_count=LIGHTFIELD_PAGE_SIZE))]

        sent_params, rows, _ = self._drive(responses)

        assert len(sent_params) == 1
        assert len(rows) == LIGHTFIELD_PAGE_SIZE

    def test_short_first_page_makes_single_request(self) -> None:
        responses = [_make_http_response(_page(["acc_1"], total_count=1))]

        sent_params, rows, _ = self._drive(responses)

        assert len(sent_params) == 1
        assert [row["id"] for row in rows] == ["acc_1"]

    def test_client_sends_required_version_header(self) -> None:
        responses = [_make_http_response(_page([], total_count=0))]

        _, _, headers = self._drive(responses)

        assert headers["Lightfield-Version"] == "2026-03-01"


class TestLightfieldSourceResponse:
    @parameterized.expand([(name,) for name in LIGHTFIELD_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        source_response = lightfield_source(
            api_key="sk_lf_test",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            api_version="2026-03-01",
        )

        assert source_response.name == endpoint
        assert source_response.primary_keys == ["id"]
        assert source_response.partition_keys == ["createdAt"]
        assert source_response.partition_mode == "datetime"


class TestCheckToken:
    @parameterized.expand(
        [
            (
                "active_key_with_scopes",
                _make_http_response({"active": True, "scopes": ["accounts:read"], "tokenType": "api_key"}),
                (True, ["accounts:read"], None),
            ),
            (
                "active_key_without_scope_list",
                _make_http_response({"active": True}),
                (True, None, None),
            ),
            (
                "inactive_key",
                _make_http_response({"active": False, "scopes": []}),
                (False, None, "This Lightfield API key is no longer active. Generate a new key and reconnect."),
            ),
            (
                "unauthorized",
                _make_http_response({"error": "unauthorized"}, status_code=401),
                (False, None, "Invalid Lightfield API key. Check the key and try again."),
            ),
            (
                "server_error",
                _make_http_response({"error": "oops"}, status_code=503),
                (False, None, "Lightfield returned an unexpected status (503) while validating the key."),
            ),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.lightfield.make_tracked_session"
    )
    def test_status_mapping(
        self,
        _name: str,
        response: Response,
        expected: tuple[bool, list[str] | None, str | None],
        mock_session: MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = response

        assert check_token("sk_lf_test", "2026-03-01") == expected

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.lightfield.make_tracked_session"
    )
    def test_probe_sends_auth_and_version_headers(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _make_http_response({"active": True, "scopes": []})

        check_token("sk_lf_test", "2026-03-01")

        _, kwargs = mock_session.return_value.get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer sk_lf_test"
        assert kwargs["headers"]["Lightfield-Version"] == "2026-03-01"
