from collections.abc import AsyncGenerator

import pytest
from fakeredis import aioredis as fakeredis
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from llm_gateway.api.admin import admin_router
from llm_gateway.config import Settings
from llm_gateway.main import http_exception_handler
from llm_gateway.rate_limiting import usage_reset
from llm_gateway.rate_limiting.usage_reset import scan_cost_usage

ADMIN_SECRET = "test-admin-secret"
HEADERS = {"x-llm-gateway-admin-secret": ADMIN_SECRET}

COST_BURST = "ratelimit:cost:user:user_cost_burst:posthog_code"
COST_SUSTAINED = "ratelimit:cost:user:user_cost_sustained:posthog_code"
REQ_BURST = "ratelimit:burst"
PRODUCT = "ratelimit:cost:product:posthog_code"


def _make_app(redis: fakeredis.FakeRedis) -> FastAPI:
    app = FastAPI()
    app.exception_handler(HTTPException)(http_exception_handler)
    app.include_router(admin_router)
    app.state.redis = redis
    return app


@pytest.fixture
async def redis() -> AsyncGenerator[fakeredis.FakeRedis, None]:
    yield fakeredis.FakeRedis()


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("llm_gateway.api.admin.get_settings", lambda: Settings(admin_secret=ADMIN_SECRET))


@pytest.fixture
async def client(redis: fakeredis.FakeRedis) -> AsyncGenerator[AsyncClient, None]:
    app = _make_app(redis)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _seed(redis: fakeredis.FakeRedis, **key_to_value: float) -> None:
    for k, v in key_to_value.items():
        await redis.set(k, v)


class TestAdminAuth:
    async def test_missing_secret_is_unauthorized(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/admin/usage/100")).status_code == 401

    async def test_wrong_secret_is_unauthorized(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/admin/usage/100", headers={"x-llm-gateway-admin-secret": "nope"})
        assert resp.status_code == 401

    async def test_disabled_when_secret_unconfigured(
        self, redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("llm_gateway.api.admin.get_settings", lambda: Settings(admin_secret=None))
        app = _make_app(redis)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # 404 hides the surface entirely when no secret is set.
            assert (await c.get("/v1/admin/usage/100", headers=HEADERS)).status_code == 404
            assert (await c.post("/v1/admin/reset/100", headers=HEADERS, json={})).status_code == 404


class TestUsageEndpoint:
    async def test_returns_live_cost_counters(self, client: AsyncClient, redis: fakeredis.FakeRedis) -> None:
        await _seed(redis, **{f"{COST_BURST}:100": 12.5, f"{COST_SUSTAINED}:100:period:0": 40.0})

        resp = await client.get("/v1/admin/usage/100", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "100"
        assert body["product"] == "posthog_code"
        scopes = {c["scope"]: c for c in body["counters"]}
        assert scopes["user_cost_burst"]["used_usd"] == 12.5
        assert scopes["user_cost_sustained"]["used_usd"] == 40.0
        assert scopes["user_cost_burst"]["base_limit_usd"] > 0

    async def test_excludes_other_users(self, client: AsyncClient, redis: fakeredis.FakeRedis) -> None:
        await _seed(redis, **{f"{COST_BURST}:100": 1.0, f"{COST_BURST}:1000": 5.0, f"{COST_BURST}:200": 9.0})

        body = (await client.get("/v1/admin/usage/100", headers=HEADERS)).json()

        assert [c["key"] for c in body["counters"]] == [f"{COST_BURST}:100"]

    async def test_empty_when_no_counters(self, client: AsyncClient) -> None:
        body = (await client.get("/v1/admin/usage/100", headers=HEADERS)).json()
        assert body["counters"] == []


class TestResetEndpoint:
    async def test_cost_only_by_default(self, client: AsyncClient, redis: fakeredis.FakeRedis) -> None:
        await _seed(redis, **{f"{COST_BURST}:100": 1.0, f"{REQ_BURST}:100": 1.0})

        resp = await client.post("/v1/admin/reset/100", headers=HEADERS, json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["cost_keys"] == 1
        assert body["request_keys"] == 0
        assert body["total_keys"] == 1
        # request-rate key survives a default (cost-only) reset.
        assert await redis.get(f"{REQ_BURST}:100") is not None
        assert await redis.get(f"{COST_BURST}:100") is None

    async def test_request_and_product_total_opt_in(self, client: AsyncClient, redis: fakeredis.FakeRedis) -> None:
        await _seed(redis, **{f"{COST_BURST}:100": 1.0, f"{REQ_BURST}:100": 1.0, PRODUCT: 1.0})

        body = (
            await client.post(
                "/v1/admin/reset/100",
                headers=HEADERS,
                json={"cost": True, "request": True, "product_total": True},
            )
        ).json()

        assert body["cost_keys"] == 1
        assert body["request_keys"] == 1
        assert body["product_total_keys"] == 1
        assert body["total_keys"] == 3

    async def test_dry_run_counts_without_deleting(self, client: AsyncClient, redis: fakeredis.FakeRedis) -> None:
        await _seed(redis, **{f"{COST_BURST}:100": 1.0})

        body = (await client.post("/v1/admin/reset/100", headers=HEADERS, json={"dry_run": True})).json()

        assert body["cost_keys"] == 1
        assert body["dry_run"] is True
        assert await redis.get(f"{COST_BURST}:100") is not None


class TestScanCostUsage:
    async def test_reads_value_and_ttl(self, redis: fakeredis.FakeRedis) -> None:
        await redis.set(f"{COST_BURST}:100", 7.5)
        await redis.set(f"{COST_SUSTAINED}:100:period:3", 3.0, ex=3600)

        usages = await scan_cost_usage(redis, "100")

        by_scope = {u.scope: u for u in usages}
        assert by_scope["user_cost_burst"].used_usd == 7.5
        assert by_scope["user_cost_sustained"].used_usd == 3.0
        assert 0 < by_scope["user_cost_sustained"].resets_in_seconds <= 3600

    async def test_ignores_unrelated_keys(self, redis: fakeredis.FakeRedis) -> None:
        await redis.set("plan:posthog_code:100", "x")
        await redis.set(f"{REQ_BURST}:100", "1")

        assert await scan_cost_usage(redis, "100") == []

    def test_base_limit_helper(self) -> None:
        assert usage_reset._base_limit_for("user_cost_burst") > 0
        assert usage_reset._base_limit_for("user_cost_sustained") > 0
        assert usage_reset._base_limit_for("unknown") == 0.0
