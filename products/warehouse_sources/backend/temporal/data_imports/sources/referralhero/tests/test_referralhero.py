from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.referralhero import (
    ReferralHeroSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.referralhero.referralhero import (
    ReferralHeroResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.referralhero.source import ReferralHeroSource


def driver() -> SourceDriver:
    return SourceDriver(ReferralHeroSource(), ReferralHeroSourceConfig(api_token="fake-token"))


def response(body: dict[str, Any], status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def page(name: str, rows: list[dict[str, Any]], total_pages: int = 1) -> ScriptedResponse:
    data: dict[str, Any] | list[dict[str, Any]] = (
        rows if name == "bonuses" else {name: rows, "pagination": {"total_pages": total_pages}}
    )
    return response({"status": "ok", "data": data})


@pytest.mark.parametrize("name", ["subscribers", "bonuses", "rewards", "coupon_groups"])
@pytest.mark.parametrize("empty", [False, True])
def test_child_tables_follow_all_campaigns(name: str, empty: bool) -> None:
    child = {"title": "Example reward", "referrals": 2} if name == "bonuses" else {"id": "example-item"}
    result = driver().run(
        name,
        [
            page("lists", [{"uuid": "MFexample001"}], 2),
            page(name, [] if empty else [child]),
            page("lists", [{"uuid": "MFexample002"}], 2),
            page(name, [] if empty else [child]),
        ],
    )

    assert result.raised is None
    assert result.rows == (
        [] if empty else [{**child, "list_uuid": "MFexample001"}, {**child, "list_uuid": "MFexample002"}]
    )
    assert len(result.requests) == 4
    for index, campaign in [(1, "MFexample001"), (3, "MFexample002")]:
        request = result.requests[index]
        assert request.path == f"/api/v2/lists/{campaign}/{name}"
        assert dict(request.query) == ({} if name == "bonuses" else {"page": ("1",)})
        assert request.headers["authorization"] == "Bearer fake-token"
    assert result.saved_states[-1].paginator_state == {
        "completed": [f"lists/MFexample001/{name}", f"lists/MFexample002/{name}"],
        "current": None,
        "child_state": None,
    }


@pytest.mark.parametrize("finished", [False, True])
def test_lists_resume(finished: bool) -> None:
    result = driver().run(
        "lists",
        [page("lists", [{"uuid": "MFexample003"}], 3)],
        resume_state=ReferralHeroResumeConfig(paginator_state={"page": 3}, finished=finished),
    )

    assert result.items == ([] if finished else [[{"uuid": "MFexample003"}]])
    if finished:
        assert result.requests == []
    else:
        assert dict(result.requests[0].query) == {"page": ("3",)}


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
    ],
)
def test_auth_errors(status: int, code: str, message: str) -> None:
    denied = response({"status": "error", "code": code, "message": "Missing API token"}, status)
    with scripted_network(always(denied)) as network:
        assert validate_credentials("fake-token") == (False, message)
    result = driver().run("lists", always(denied))
    assert isinstance(result.raised, HTTPError)
    errors = ReferralHeroSource().get_non_retryable_errors()
    assert next(value for pattern, value in errors.items() if pattern in str(result.raised)) == message
    assert len(network.requests_log) == 1
    assert len(result.requests) == 1


def test_validate_credentials_only_reads_first_page() -> None:
    with scripted_network([page("lists", [{"uuid": "MFexample001"}], 100)]) as network:
        assert validate_credentials("fake-token") == (True, None)

    assert len(network.requests_log) == 1
    assert network.requests_log[0].read_timeout == 60.0
    assert network.requests_log[0].headers["authorization"] == "Bearer fake-token"


def test_unknown_errors_are_not_invalid_credentials() -> None:
    with scripted_network(always(response({"code": "bad_request"}, 400))):
        with pytest.raises(HTTPError):
            validate_credentials("fake-token")


def test_malformed_success_does_not_silently_replace_table() -> None:
    result = driver().run("lists", [response({"status": "ok", "data": {"unexpected": []}})])

    assert isinstance(result.raised, ValueError)
