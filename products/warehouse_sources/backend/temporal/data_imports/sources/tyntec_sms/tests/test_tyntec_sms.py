import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import patch

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.settings import (
    MAX_REQUEST_IDS,
    MESSAGE_STATUS,
    PHONE_NUMBERS,
    PHONEBOOK_MAX_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.tyntec_sms import (
    parse_request_ids,
    tyntec_sms_source,
    validate_credentials,
)


def _make_http_response(body: dict[str, Any], status_code: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.reason = reason
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.tyntec.com/"
    return resp


def _drive(endpoint: str, responses: list[Response], request_ids: str | None = None) -> tuple[list[Any], list[dict]]:
    """Run ``tyntec_sms_source`` against a mocked HTTP session.

    Returns ``(rows, sent_requests)`` where each sent request is captured as
    ``{"url": ..., "params": ...}`` at send time (the Request object is mutated
    between pages, so call_args_list can't be trusted).
    """
    sent: list[dict] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **kwargs: Any) -> Response:
        sent.append(
            {
                "url": request.url,
                "params": dict(request.params or {}),
                "allow_redirects": kwargs.get("allow_redirects"),
            }
        )
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
    ) as MockSession:
        mock_session = MockSession.return_value
        mock_session.headers = {}
        mock_session.prepare_request.side_effect = lambda req: req
        mock_session.send.side_effect = fake_send

        source_response = tyntec_sms_source(
            api_key="test-key",
            endpoint=endpoint,
            team_id=123,
            job_id="test_job",
            request_ids=request_ids,
        )
        rows: list[Any] = []
        for page in cast(Iterable[Any], source_response.items()):
            if isinstance(page, list):
                rows.extend(page)
            else:
                rows.append(page)
        return rows, sent


class TestParseRequestIds:
    def test_caps_list_to_bound_worker_time(self) -> None:
        # Each id is one serial HTTP request per sync; an unbounded list would let a single
        # source occupy an import worker indefinitely.
        raw = ",".join(f"id-{i}" for i in range(MAX_REQUEST_IDS + 5))

        parsed = parse_request_ids(raw)

        assert len(parsed) == MAX_REQUEST_IDS
        assert parsed[0] == "id-0"
        assert parsed[-1] == f"id-{MAX_REQUEST_IDS - 1}"


class TestMessageStatus:
    def test_request_id_is_url_quoted(self) -> None:
        responses = [_make_http_response({"requestId": "a/b"})]
        _, sent = _drive(MESSAGE_STATUS, responses, request_ids="a/b")

        assert sent[0]["url"] == "https://api.tyntec.com/messaging/v1/messages/a%2Fb"

    def test_expired_request_id_404_is_skipped(self) -> None:
        # tyntec drops statuses ~3 months after delivery; an expired id must not fail the sync.
        responses = [
            _make_http_response({"title": "Not Found"}, status_code=404, reason="Not Found"),
            _make_http_response({"requestId": "id-2", "status": "DELIVERED"}),
        ]
        rows, sent = _drive(MESSAGE_STATUS, responses, request_ids="id-1, id-2")

        assert [row["requestId"] for row in rows] == ["id-2"]
        assert len(sent) == 2

    def test_auth_error_is_not_swallowed_by_404_skip(self) -> None:
        responses = [
            _make_http_response({"message": "No API key found in request"}, status_code=401, reason="Unauthorized")
        ]

        with pytest.raises(HTTPError, match="401 Client Error"):
            _drive(MESSAGE_STATUS, responses, request_ids="id-1")

    def test_no_request_ids_yields_nothing_without_requests(self) -> None:
        rows, sent = _drive(MESSAGE_STATUS, [], request_ids=None)

        assert rows == []
        assert sent == []


class TestListEndpoints:
    def test_phone_numbers_requests_full_documented_cap(self) -> None:
        _, sent = _drive(PHONE_NUMBERS, [_make_http_response({"provisioningRequests": [], "size": 0})])

        assert sent[0]["params"] == {"size": PHONEBOOK_MAX_SIZE}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, True),
            # Unknown probe id with a valid key answers 404.
            (404, True),
            # Missing key at the gateway.
            (401, False),
            # Invalid key at the gateway.
            (403, False),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.tyntec_sms.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.get.return_value = _make_http_response({}, status_code=status_code)

            assert validate_credentials("test-key") is expected

            _, kwargs = mock_session.get.call_args
            assert kwargs["headers"] == {"apikey": "test-key"}
            assert kwargs["allow_redirects"] is False
