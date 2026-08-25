from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from llm_gateway.db.required_tables import REQUIRED_TABLES
from llm_gateway.main import create_app


class TestHealthEndpoints:
    @pytest.fixture
    def client_with_healthy_db(self, mock_db_pool: MagicMock) -> TestClient:
        app = create_app()
        app.state.db_pool = mock_db_pool
        return TestClient(app)

    @pytest.fixture
    def client_with_unhealthy_db(self) -> TestClient:
        app = create_app()
        pool = MagicMock()
        pool.acquire = AsyncMock(side_effect=Exception("Connection failed"))
        pool.release = AsyncMock()
        app.state.db_pool = pool
        return TestClient(app)

    @pytest.fixture
    def client_with_missing_privileges(self, mock_db_pool: MagicMock) -> TestClient:
        app = create_app()
        conn = mock_db_pool.acquire.return_value
        conn.fetch = AsyncMock(return_value=[{"table_name": "posthog_team"}, {"table_name": "ee_role"}])
        app.state.db_pool = mock_db_pool
        return TestClient(app)

    @pytest.mark.parametrize(
        "endpoint,expected_status,expected_body",
        [
            pytest.param("/", 200, {"service": "llm-gateway", "status": "running"}, id="root"),
            pytest.param("/_liveness", 200, {"status": "alive"}, id="liveness"),
            pytest.param("/_readiness", 200, {"status": "ready"}, id="readiness"),
        ],
    )
    def test_healthy_endpoints(
        self,
        client_with_healthy_db: TestClient,
        endpoint: str,
        expected_status: int,
        expected_body: dict,
    ) -> None:
        response = client_with_healthy_db.get(endpoint)
        assert response.status_code == expected_status
        assert response.json() == expected_body

    def test_readiness_fails_when_db_unavailable(self, client_with_unhealthy_db: TestClient) -> None:
        response = client_with_unhealthy_db.get("/_readiness")
        assert response.status_code == 503
        assert response.json()["detail"] == "Database not ready"

    def test_readiness_fails_when_privileges_missing(
        self, client_with_missing_privileges: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        response = client_with_missing_privileges.get("/_readiness")
        assert response.status_code == 503
        # Same body as the connection-failure branch, deliberately.
        assert response.json()["detail"] == "Database not ready"
        assert "posthog_team, ee_role" in caplog.text
        assert "posthog-cloud-infra" in caplog.text

    def test_readiness_checks_every_required_table(
        self, client_with_healthy_db: TestClient, mock_db_pool: MagicMock
    ) -> None:
        client_with_healthy_db.get("/_readiness")
        conn = mock_db_pool.acquire.return_value
        conn.fetch.assert_awaited_once()
        checked_tables = conn.fetch.await_args.args[1]
        assert checked_tables == sorted(REQUIRED_TABLES)

    def test_liveness_succeeds_when_db_unavailable(self, client_with_unhealthy_db: TestClient) -> None:
        response = client_with_unhealthy_db.get("/_liveness")
        assert response.status_code == 200
