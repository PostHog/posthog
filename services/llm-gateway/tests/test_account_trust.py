from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from llm_gateway.auth.cache import reset_auth_cache
from llm_gateway.auth.service import get_auth_service
from llm_gateway.products.config import POSTHOG_CODE_US_APP_ID
from llm_gateway.services.account_trust import AccountTrust, AccountTrustResolver
from tests.conftest import create_test_app


@pytest.mark.parametrize(
    "age,score,allowed",
    [
        (timedelta(days=-1), 3, False),
        (timedelta(0), 7, True),
        (timedelta(days=7, microseconds=-1), 3, False),
        (timedelta(days=7, microseconds=-1), 7, True),
        (timedelta(days=7), 3, True),
        (timedelta(days=7), 0, False),
        (timedelta(days=30, microseconds=-1), 0, False),
        (timedelta(days=30, microseconds=-1), 3, True),
        (timedelta(days=30), 0, True),
        (timedelta(days=365), 0, True),
    ],
)
def test_trust_requirement_changes_at_age_boundaries(age: timedelta, score: int, allowed: bool) -> None:
    now = datetime(2026, 10, 2, tzinfo=UTC)
    trust = AccountTrust(created_at=now - age, score=score)

    assert trust.allows_requests(now) is allowed


@pytest.mark.parametrize(
    "scores,expected",
    [
        ({"events": 7, "ai_credits": 0}, 7),
        ('{"events": 3, "ai_credits": 10}', 10),
        ({}, 0),
        (None, 0),
        ("invalid", 0),
        ([15], 0),
        ({"events": "15", "ai_credits": True, "other": -1}, 0),
    ],
)
async def test_resolves_highest_valid_product_score(mock_db_pool: MagicMock, scores: object, expected: int) -> None:
    created_at = datetime.now(UTC)
    mock_db_pool.acquire.return_value.fetchrow.return_value = {
        "created_at": created_at,
        "customer_trust_scores": scores,
    }

    trust = await AccountTrustResolver(mock_db_pool).resolve(42)

    assert trust == AccountTrust(created_at=created_at, score=expected)


async def test_cache_preserves_age_boundaries_and_refreshes_score(mock_db_pool: MagicMock) -> None:
    now = datetime(2026, 10, 2, tzinfo=UTC)
    conn = mock_db_pool.acquire.return_value
    conn.fetchrow.return_value = {
        "created_at": now - timedelta(days=7, seconds=-1),
        "customer_trust_scores": {"events": 3},
    }
    with patch("llm_gateway.services.account_trust.time.monotonic", return_value=100) as clock:
        resolver = AccountTrustResolver(mock_db_pool)
        trust = await resolver.resolve(42)
        assert trust is not None and not trust.allows_requests(now)
        cached = await resolver.resolve(42)
        assert cached is not None and cached.allows_requests(now + timedelta(seconds=1))
        assert conn.fetchrow.await_count == 1

        conn.fetchrow.return_value = {"created_at": now, "customer_trust_scores": {"events": 0}}
        clock.return_value = 160
        refreshed = await resolver.resolve(42)
        assert refreshed is not None and not refreshed.allows_requests(now + timedelta(seconds=1))
        assert conn.fetchrow.await_count == 2


@pytest.fixture(autouse=True)
def clear_auth_cache() -> Generator[None]:
    reset_auth_cache()
    get_auth_service.cache_clear()
    yield
    reset_auth_cache()
    get_auth_service.cache_clear()


@pytest.mark.parametrize(
    "path",
    [
        "/v1/chat/completions",
        "/v1/responses",
        "/v1/messages",
        "/v1/messages/count_tokens",
        "/v1/audio/transcriptions",
    ],
)
def test_inference_routes_deny_low_trust_before_dispatch(mock_db_pool: MagicMock, path: str) -> None:
    conn = mock_db_pool.acquire.return_value
    conn.fetchrow.return_value = {
        "user_id": 1,
        "current_team_id": 42,
        "distinct_id": "test-user",
        "scopes": ["llm_gateway:read"],
        "is_staff": True,
        "created_at": datetime.now(UTC),
        "customer_trust_scores": {"events": 3},
    }
    app = create_test_app(mock_db_pool, account_trust_db_pool=mock_db_pool)
    with TestClient(app) as client, patch("llm_gateway.api.openai.litellm.acompletion") as completion:
        response = client.post(path, json={}, headers={"Authorization": "Bearer phx_test_trust"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_trust_required"
    completion.assert_not_called()


@pytest.mark.parametrize("lookup", [None, RuntimeError("database unavailable")])
def test_unresolvable_account_returns_retryable_error(mock_db_pool: MagicMock, lookup: object) -> None:
    conn = mock_db_pool.acquire.return_value
    conn.fetchrow.side_effect = [
        {
            "user_id": 1,
            "current_team_id": 42,
            "distinct_id": "test-user",
            "scopes": ["llm_gateway:read"],
            "is_staff": False,
        },
        lookup,
    ]
    app = create_test_app(mock_db_pool, account_trust_db_pool=mock_db_pool)
    with TestClient(app) as client:
        response = client.post("/v1/chat/completions", json={}, headers={"Authorization": "Bearer phx_test_trust"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "account_trust_unavailable"


def test_oauth_checks_selected_project_even_for_internal_runs(mock_db_pool: MagicMock) -> None:
    now = datetime.now(UTC)
    conn = mock_db_pool.acquire.return_value

    async def fetchrow(query: str, *args: object) -> dict[str, object]:
        if "posthog_oauthaccesstoken" in query:
            return {
                "user_id": 1,
                "current_team_id": 1,
                "distinct_id": "test-user",
                "is_staff": False,
                "scope": "llm_gateway:read internal_run:read",
                "expires": now + timedelta(hours=1),
                "application_id": POSTHOG_CODE_US_APP_ID,
                "scoped_teams": [1, 42],
                "scoped_organizations": [],
            }
        if "posthog_organizationmembership" in query:
            return {"organization_id": "test-org", "membership_id": 1, "membership_level": 8}
        return {
            "created_at": now if args[0] == 42 else now - timedelta(days=31),
            "customer_trust_scores": {},
        }

    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    app = create_test_app(mock_db_pool, account_trust_db_pool=mock_db_pool)
    with TestClient(app) as client:
        original_project = client.post(
            "/posthog_code/v1/chat/completions",
            json={},
            headers={"Authorization": "Bearer pha_test_trust"},
        )
        response = client.post(
            "/posthog_code/v1/chat/completions",
            json={},
            headers={"Authorization": "Bearer pha_test_trust", "X-PostHog-Project-Id": "42"},
        )

    assert original_project.status_code == 422
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_trust_required"


@pytest.mark.parametrize(
    "is_staff,current_team_id,override,expected_status",
    [
        (True, 1, "42", 403),
        (False, 42, "1", 403),
        (True, 42, "invalid", 403),
        (True, 42, "1", 422),
    ],
)
def test_only_staff_keys_can_select_customer_account(
    mock_db_pool: MagicMock, is_staff: bool, current_team_id: int, override: str, expected_status: int
) -> None:
    now = datetime.now(UTC)
    conn = mock_db_pool.acquire.return_value

    async def fetchrow(query: str, *args: object) -> dict[str, object]:
        if "posthog_personalapikey" in query:
            return {
                "user_id": 1,
                "current_team_id": current_team_id,
                "distinct_id": "test-user",
                "scopes": ["llm_gateway:read"],
                "is_staff": is_staff,
            }
        return {
            "created_at": now if args[0] == 42 else now - timedelta(days=31),
            "customer_trust_scores": {},
        }

    conn.fetchrow = AsyncMock(side_effect=fetchrow)
    app = create_test_app(mock_db_pool, account_trust_db_pool=mock_db_pool)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={},
            headers={"Authorization": "Bearer phx_test_trust", "X-PostHog-Property-Team_Id": override},
        )

    assert response.status_code == expected_status
    if expected_status == 403:
        assert response.json()["error"]["code"] == "account_trust_required"
