import json
import dataclasses
from collections.abc import Iterable
from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Request, Response
from requests.exceptions import ConnectionError as RequestsConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.lingo_dev import (
    LingoDevPaginator,
    LingoDevResumeConfig,
    lingo_dev_source,
    validate_credentials,
)


class TestLingoDevPaginator:
    @parameterized.expand(
        [
            ("more_pages", {"items": [{"id": "ljb_1"}], "nextCursor": "cur_2"}, True),
            ("last_page_null_cursor", {"items": [{"id": "ljb_1"}], "nextCursor": None}, False),
            ("missing_cursor_key", {"items": []}, False),
        ]
    )
    def test_update_state(self, label: str, response_body: Any, has_next: bool) -> None:
        paginator = LingoDevPaginator()
        response = MagicMock()
        response.json.return_value = response_body

        paginator.update_state(response)

        assert paginator.has_next_page is has_next

    def test_update_request_sets_cursor_param(self) -> None:
        paginator = LingoDevPaginator()
        response = MagicMock()
        response.json.return_value = {"items": [{"id": "ljb_1"}], "nextCursor": "cur_2"}
        paginator.update_state(response)

        request = Request(method="GET", url="https://api.lingo.dev/jobs/localization", params={"limit": 100})
        paginator.update_request(request)

        assert request.params["cursor"] == "cur_2"

    @parameterized.expand(
        [
            ("fresh_run_omits_cursor", None, None),
            ("resumed_sets_cursor", "cur_42", "cur_42"),
        ]
    )
    def test_init_request(self, label: str, seeded_cursor: str | None, expected_cursor_param: str | None) -> None:
        paginator = LingoDevPaginator()
        if seeded_cursor is not None:
            paginator.set_resume_state({"cursor": seeded_cursor})

        request = Request(method="GET", url="https://api.lingo.dev/jobs/localization", params={"limit": 100})
        paginator.init_request(request)

        if expected_cursor_param is None:
            assert "cursor" not in (request.params or {})
        else:
            assert request.params["cursor"] == expected_cursor_param

    def test_resume_state_round_trip(self) -> None:
        paginator = LingoDevPaginator()
        paginator.set_resume_state({"cursor": "cur_42"})

        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"cursor": "cur_42"}

    def test_set_resume_state_ignores_missing_cursor(self) -> None:
        paginator = LingoDevPaginator()
        paginator.set_resume_state({})

        assert paginator.get_resume_state() is None


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(ids: list[str], next_cursor: str | None) -> dict[str, Any]:
    return {
        "items": [
            {"id": i, "groupId": "ljg_1", "targetLocale": "ja", "status": "completed", "createdAt": "2026-01-01"}
            for i in ids
        ],
        "nextCursor": next_cursor,
    }


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid_key", _make_http_response(_page(["ljb_1"], None)), True, None),
            (
                "invalid_key_json_message",
                _make_http_response({"_tag": "UnauthorizedError", "message": "Invalid API key"}, status_code=401),
                False,
                "Invalid API key",
            ),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.lingo_dev.make_tracked_session")
    def test_status_mapping(
        self,
        label: str,
        response: Response,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = response

        is_valid, message = validate_credentials("test-key")

        assert is_valid is expected_valid
        assert message == expected_message

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.lingo_dev.make_tracked_session")
    def test_network_error_returns_error_message(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = RequestsConnectionError("connection refused")

        is_valid, message = validate_credentials("test-key")

        assert is_valid is False
        assert message is not None and "connection refused" in message


class TestLingoDevSourceResumeBehavior:
    """End-to-end resume behaviour through the shared ``rest_api_resource`` path."""

    def _drive(
        self, manager: MagicMock, responses: list[Response]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Drive ``lingo_dev_source`` with a mocked HTTP session, returning the params
        sent with each request (shallow copies — the paginator mutates the Request
        in-place between pages) and the rows yielded."""
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

            source_response = lingo_dev_source(
                api_key="test-key",
                endpoint="jobs",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            rows = [row for page in cast(Iterable[Any], source_response.items()) for row in page]
            return sent_params, rows

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_page(["ljb_1", "ljb_2"], "cur_2")),
            _make_http_response(_page(["ljb_3"], "cur_3")),
            _make_http_response(_page(["ljb_4"], None)),
        ]
        sent_params, rows = self._drive(manager, responses)

        # First request omits the cursor (fresh run); subsequent requests carry the
        # cursor from the previous response — a paginator that re-sends the same
        # cursor would loop on one page forever.
        assert [p.get("cursor") for p in sent_params] == [None, "cur_2", "cur_3"]
        assert [row["id"] for row in rows] == ["ljb_1", "ljb_2", "ljb_3", "ljb_4"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            LingoDevResumeConfig(cursor="cur_2"),
            LingoDevResumeConfig(cursor="cur_3"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = LingoDevResumeConfig(cursor="cur_3")

        responses = [
            _make_http_response(_page(["ljb_4"], None)),
        ]
        sent_params, _ = self._drive(manager, responses)

        # The very first request goes out at the resumed cursor — no cursor-less
        # call that would re-fetch the already-synced pages.
        assert [p.get("cursor") for p in sent_params] == ["cur_3"]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_page(["ljb_1"], None)),
        ]
        self._drive(manager, responses)

        manager.save_state.assert_not_called()

    def test_source_response_shape(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        source_response = lingo_dev_source(
            api_key="test-key",
            endpoint="jobs",
            team_id=123,
            job_id="test_job",
            resumable_source_manager=manager,
        )

        assert source_response.name == "jobs"
        assert source_response.primary_keys == ["id"]
        assert source_response.partition_keys == ["createdAt"]
        assert source_response.partition_mode == "datetime"
        assert source_response.sort_mode == "desc"

    def test_resume_config_serialization_round_trip(self) -> None:
        cfg = LingoDevResumeConfig(cursor="cur_42")

        as_dict = dataclasses.asdict(cfg)
        restored = LingoDevResumeConfig(**as_dict)

        assert restored == cfg
