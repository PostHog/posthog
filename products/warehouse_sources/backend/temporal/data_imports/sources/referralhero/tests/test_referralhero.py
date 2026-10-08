import json
from collections.abc import Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response, Session
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.referralhero.referralhero import (
    ReferralHeroResumeConfig,
    referralhero_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.referralhero.source import ReferralHeroSource


def batches(source: SourceResponse) -> Iterable[list[dict[str, Any]]]:
    return cast(Iterable[list[dict[str, Any]]], source.items())


@pytest.fixture
def transport() -> Iterator[MagicMock]:
    with Session() as session:
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
                return_value=session,
            ),
            patch.object(session, "send") as send,
        ):
            yield send


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock()
    result.load_state.return_value = None
    return result


def response(body: dict[str, Any], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.url = "https://app.referralhero.com/api/v2/lists"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


def page(name: str, rows: list[dict[str, Any]], total_pages: int = 1) -> Response:
    data: dict[str, Any] | list[dict[str, Any]] = (
        rows if name == "bonuses" else {name: rows, "pagination": {"total_pages": total_pages}}
    )
    return response({"status": "ok", "data": data})


@pytest.mark.parametrize("name", ["subscribers", "bonuses", "rewards", "coupon_groups"])
@pytest.mark.parametrize("empty", [False, True])
def test_child_tables_follow_all_campaigns(transport: MagicMock, manager: MagicMock, name: str, empty: bool) -> None:
    child = {"title": "Example reward", "referrals": 2} if name == "bonuses" else {"id": "example-item"}
    transport.side_effect = [
        page("lists", [{"uuid": "MFexample001"}], 2),
        page(name, [] if empty else [child]),
        page("lists", [{"uuid": "MFexample002"}], 2),
        page(name, [] if empty else [child]),
    ]
    source = referralhero_source("fake-token", name, 1, "job", manager)
    rows = [row for batch in batches(source) for row in batch]

    assert rows == ([] if empty else [{**child, "list_uuid": "MFexample001"}, {**child, "list_uuid": "MFexample002"}])
    assert transport.call_count == 4
    for index, campaign in [(1, "MFexample001"), (3, "MFexample002")]:
        request = transport.call_args_list[index].args[0]
        assert urlsplit(request.url).path == f"/api/v2/lists/{campaign}/{name}"
        assert parse_qs(urlsplit(request.url).query) == ({} if name == "bonuses" else {"page": ["1"]})
        assert request.headers["Authorization"] == "Bearer fake-token"
    assert manager.save_state.call_args.args[0].paginator_state == {
        "completed": [f"lists/MFexample001/{name}", f"lists/MFexample002/{name}"],
        "current": None,
        "child_state": None,
    }


@pytest.mark.parametrize("finished", [False, True])
def test_lists_resume(transport: MagicMock, manager: MagicMock, finished: bool) -> None:
    manager.load_state.return_value = ReferralHeroResumeConfig(paginator_state={"page": 3}, finished=finished)
    transport.side_effect = [page("lists", [{"uuid": "MFexample003"}], 3)]
    source = referralhero_source("fake-token", "lists", 1, "job", manager)
    assert list(batches(source)) == ([] if finished else [[{"uuid": "MFexample003"}]])
    if finished:
        transport.assert_not_called()
    else:
        assert parse_qs(urlsplit(transport.call_args.args[0].url).query) == {"page": ["3"]}


@pytest.mark.parametrize(
    "status,code,message",
    [
        (400, "no_token", "Enter your ReferralHero API token from Account > API."),
        (400, "invalid_token", "Your ReferralHero API token is invalid. Copy the token from Account > API."),
        (
            400,
            "inactive_account",
            "Your ReferralHero account is inactive. Activate your account before you connect it.",
        ),
        (401, "unauthorized", "Your ReferralHero API token is invalid. Copy the token from Account > API."),
        (403, "forbidden", "ReferralHero denied access. Check your account status and API token."),
    ],
)
def test_auth_errors(transport: MagicMock, manager: MagicMock, status: int, code: str, message: str) -> None:
    transport.return_value = response({"status": "error", "code": code, "message": "Missing API token"}, status)
    assert validate_credentials("fake-token") == (False, message)
    source = referralhero_source("fake-token", "lists", 1, "job", manager)
    with pytest.raises(HTTPError) as error:
        list(batches(source))
    errors = ReferralHeroSource().get_non_retryable_errors()
    assert next(value for pattern, value in errors.items() if pattern in str(error.value)) == message
    assert transport.call_count == 2


def test_validate_credentials_only_reads_first_page(transport: MagicMock) -> None:
    transport.return_value = page("lists", [{"uuid": "MFexample001"}], 100)
    assert validate_credentials("fake-token") == (True, None)
    assert transport.call_count == 1
    assert transport.call_args.kwargs["timeout"] == (10, 60)
    assert transport.call_args.args[0].headers["Authorization"] == "Bearer fake-token"


def test_unknown_errors_are_not_invalid_credentials(transport: MagicMock) -> None:
    transport.return_value = response({"code": "bad_request"}, 400)
    with pytest.raises(HTTPError):
        validate_credentials("fake-token")


def test_unknown_table(manager: MagicMock) -> None:
    with pytest.raises(ValueError, match="Unknown ReferralHero table"):
        referralhero_source("fake-token", "missing", 1, "job", manager)


def test_malformed_success_does_not_silently_replace_table(transport: MagicMock, manager: MagicMock) -> None:
    transport.return_value = response({"status": "ok", "data": {"unexpected": []}})
    source = referralhero_source("fake-token", "lists", 1, "job", manager)
    with pytest.raises(ValueError):
        list(batches(source))
