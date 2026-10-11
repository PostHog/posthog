import json
from collections.abc import Iterable
from typing import Any, cast

from unittest.mock import MagicMock, patch

from requests import Response

from sources.demo_acme.source import DemoAcmeResumeConfig, demo_acme_source
from sources.sdk import ResumableSourceManager


def _response(rows: list[dict[str, Any]]) -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps({"data": rows}).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def test_resume_starts_at_the_saved_page_and_checkpoints_each_next_page() -> None:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = True
    manager.load_state.return_value = DemoAcmeResumeConfig(next_page=3)
    responses = iter([_response([{"id": 1}]), _response([{"id": 2}]), _response([])])
    sent_pages: list[Any] = []

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent_pages.append((request.params or {}).get("page"))
        return next(responses)

    with patch("sources.demo_acme.source.make_tracked_session") as make_session:
        session = make_session.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: request
        session.send.side_effect = fake_send

        resource = demo_acme_source(
            api_key="test-key", endpoint="Widgets", team_id=1, job_id="job-1", resumable_source_manager=manager
        )
        rows = list(cast(Iterable[Any], resource))

    assert sent_pages == [3, 4, 5]
    assert len(rows) == 2
    assert [call.args[0] for call in manager.save_state.call_args_list] == [
        DemoAcmeResumeConfig(next_page=4),
        DemoAcmeResumeConfig(next_page=5),
    ]
