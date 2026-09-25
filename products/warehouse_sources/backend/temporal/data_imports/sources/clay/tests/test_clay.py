import json
from collections.abc import Iterable
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.clay.clay import (
    REQUEST_TIMEOUT_SECONDS,
    ClayResumeConfig,
    clay_source,
    flatten_record,
    parse_table_ids,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

TABLE_ID = "t_0te9i4tZEHwc9hihBXu"


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (TABLE_ID, [TABLE_ID]),
        (f"https://app.clay.com/workspaces/123/workbooks/wb_abc/tables/{TABLE_ID}/views/gv_xyz", [TABLE_ID]),
        (f"{TABLE_ID}, t_second\n  t_third\n{TABLE_ID}", [TABLE_ID, "t_second", "t_third"]),
        ("not a table id", []),
        ("", []),
    ],
)
def test_parse_table_ids(raw: str, expected: list[str]) -> None:
    assert parse_table_ids(raw) == expected


def test_flatten_record() -> None:
    record = {
        "Domain": {"status": "success", "value": "clay.com", "fields": None},
        "Enrich Company": {"status": "success", "value": "Clay", "fields": {"employee_count": 500}},
        "Work Email": {"status": "error", "error": "Provider request failed"},
        "Phone": {"status": "running"},
        "Notes": {"status": "empty"},
        "Owner_fields": {"status": "success", "value": "user column", "fields": None},
        "Owner": {"status": "success", "value": "Ada", "fields": {"title": "CEO"}},
    }

    assert flatten_record(record) == {
        "Domain": "clay.com",
        "Enrich Company": "Clay",
        "Enrich Company_fields": {"employee_count": 500},
        "Work Email": None,
        "Phone": None,
        "Notes": None,
        "Owner": "Ada",
        "Owner_fields": "user column",
    }


class TestClaySourceBehavior:
    def _drive(
        self, manager: MagicMock, responses: list[Response]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], MagicMock]:
        sent_bodies: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_bodies.append(json.loads(json.dumps(request.json or {})))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = clay_source(
                api_key="clay_test_key",
                table_id=TABLE_ID,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            rows = [row for page in cast(Iterable[Any], source_response.items()) for row in page]
            return sent_bodies, rows, mock_session

    def test_pages_with_body_cursor_and_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(
                {"data": [{"Domain": {"status": "success", "value": "a.com", "fields": None}}], "cursor": "c1"}
            ),
            _make_http_response({"data": [{"Domain": {"status": "success", "value": "b.com", "fields": None}}]}),
        ]
        sent_bodies, rows, mock_session = self._drive(manager, responses)

        assert [body.get("cursor") for body in sent_bodies] == [None, "c1"]
        assert all(
            body["query"] == {"tables": [{"id": TABLE_ID}], "field_mode": "names"} and body["limit"] == 100
            for body in sent_bodies
        )
        assert rows == [{"Domain": "a.com"}, {"Domain": "b.com"}]
        assert [call.args[0] for call in manager.save_state.call_args_list] == [ClayResumeConfig(next_cursor="c1")]
        sent_request = mock_session.send.call_args_list[0].args[0]
        assert sent_request.method == "POST"
        assert sent_request.prepare().headers["clay-api-key"] == "clay_test_key"
        assert all(call.kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS for call in mock_session.send.call_args_list)

    def test_resume_sends_saved_cursor_on_first_request(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ClayResumeConfig(next_cursor="resumed")

        sent_bodies, _, _ = self._drive(manager, [_make_http_response({"data": []})])

        assert [body.get("cursor") for body in sent_bodies] == ["resumed"]


@pytest.mark.parametrize(
    ("me_status", "table_status", "expected_valid", "expected_message_part"),
    [
        (200, 200, True, None),
        (401, None, False, "rejected the API key"),
        (500, None, False, "unexpected status (500)"),
        (200, 403, False, "Enterprise plan"),
        (200, 404, False, "could not find table"),
        (200, 422, False, "unexpected status (422)"),
    ],
)
def test_validate_credentials(
    me_status: int, table_status: Optional[int], expected_valid: bool, expected_message_part: Optional[str]
) -> None:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.clay.clay.make_tracked_session"
    ) as MockSession:
        session = MockSession.return_value
        session.get.return_value = _make_http_response({}, me_status)
        session.post.return_value = _make_http_response({"data": []}, table_status or 200)

        valid, message = validate_credentials("clay_test_key", [TABLE_ID])

    assert valid is expected_valid
    if expected_message_part is None:
        assert message is None
    else:
        assert message is not None and expected_message_part in message


def test_validate_credentials_requires_a_table_id() -> None:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.clay.clay.make_tracked_session"
    ) as MockSession:
        valid, message = validate_credentials("clay_test_key", [])

    assert valid is False
    assert message == "Enter at least one Clay table ID or table URL."
    MockSession.assert_not_called()
