import os

import pytest
import structlog
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect
from structlog.testing import capture_logs

from llm_gateway.config import Settings, get_settings
from llm_gateway.main import RequestLoggingMiddleware, export_provider_credentials

_EXPORTED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "AWS_REGION",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENROUTER_API_KEY",
    "FIREWORKS_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Start each test from a clean slate so leakage from the surrounding shell
    # (or earlier tests) can't make a missing export look like a passing one.
    for var in _EXPORTED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()


class TestExportProviderCredentials:
    @pytest.mark.parametrize(
        "setting_name,setting_value,expected_env,expected_value",
        [
            pytest.param(
                "openai_organization",
                "org-test-fixture",
                "OPENAI_ORG_ID",
                "org-test-fixture",
                id="openai_organization_to_OPENAI_ORG_ID",
            ),
            pytest.param(
                "openai_api_base_url",
                "https://eu.api.openai.com/v1",
                "OPENAI_BASE_URL",
                "https://eu.api.openai.com/v1",
                id="openai_api_base_url_to_OPENAI_BASE_URL",
            ),
            pytest.param(
                "openai_api_key",
                "sk-test",
                "OPENAI_API_KEY",
                "sk-test",
                id="openai_api_key_to_OPENAI_API_KEY",
            ),
            pytest.param(
                "anthropic_api_key",
                "sk-ant-test",
                "ANTHROPIC_API_KEY",
                "sk-ant-test",
                id="anthropic_api_key_to_ANTHROPIC_API_KEY",
            ),
            pytest.param(
                "bedrock_region_name",
                "eu-central-1",
                "AWS_REGION",
                "eu-central-1",
                id="bedrock_region_name_to_AWS_REGION",
            ),
            pytest.param(
                "openrouter_api_key",
                "sk-or-test",
                "OPENROUTER_API_KEY",
                "sk-or-test",
                id="openrouter_api_key_to_OPENROUTER_API_KEY",
            ),
            pytest.param(
                "fireworks_api_key",
                "fw-test",
                "FIREWORKS_API_KEY",
                "fw-test",
                id="fireworks_api_key_to_FIREWORKS_API_KEY",
            ),
        ],
    )
    def test_exports_setting_to_env_var(
        self,
        setting_name: str,
        setting_value: str,
        expected_env: str,
        expected_value: str,
    ) -> None:
        # model_validate lets us construct from a parametrized dict without
        # tripping mypy on the kwargs spread (Settings has per-field types,
        # so dict[str, str] is rejected by **kwargs typing).
        settings = Settings.model_validate({setting_name: setting_value})

        export_provider_credentials(settings)

        assert os.environ.get(expected_env) == expected_value

    @pytest.mark.parametrize(
        "env_var",
        _EXPORTED_ENV_VARS,
    )
    def test_unset_settings_do_not_touch_env(self, env_var: str) -> None:
        # When the setting is unset, the corresponding env var must remain unset —
        # otherwise an empty default could shadow ambient credentials (e.g. AWS_REGION
        # from IRSA) or attribute traffic to the wrong OpenAI org.
        settings = Settings()

        export_provider_credentials(settings)

        assert env_var not in os.environ

    def test_does_not_overwrite_existing_env_when_setting_is_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # If LLM_GATEWAY_OPENAI_ORGANIZATION is not set, an org id that was
        # already present in the environment (e.g. set by the runtime) must
        # survive untouched.
        monkeypatch.setenv("OPENAI_ORG_ID", "org-preset-by-runtime")
        settings = Settings()

        export_provider_credentials(settings)

        assert os.environ["OPENAI_ORG_ID"] == "org-preset-by-runtime"

    def test_settings_picks_up_env_prefixed_organization(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # End-to-end: LLM_GATEWAY_OPENAI_ORGANIZATION → Settings.openai_organization
        # → OPENAI_ORG_ID, which is what litellm / the OpenAI SDK read.
        monkeypatch.setenv("LLM_GATEWAY_OPENAI_ORGANIZATION", "org-test-fixture")
        get_settings.cache_clear()

        settings = get_settings()
        assert settings.openai_organization == "org-test-fixture"

        export_provider_credentials(settings)
        assert os.environ["OPENAI_ORG_ID"] == "org-test-fixture"

    def test_settings_picks_up_env_prefixed_base_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LLM_GATEWAY_OPENAI_API_BASE_URL", "https://eu.api.openai.com/v1")
        get_settings.cache_clear()

        settings = get_settings()
        assert settings.openai_api_base_url == "https://eu.api.openai.com/v1"

        export_provider_credentials(settings)
        assert os.environ["OPENAI_BASE_URL"] == "https://eu.api.openai.com/v1"


def _middleware_test_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    def refuse_to_read_postgres() -> None:
        raise RuntimeError("permission denied for table posthog_team")

    @app.get("/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/raises", dependencies=[Depends(refuse_to_read_postgres)])
    def raises() -> dict[str, bool]:
        return {"ok": True}

    def abandon_request() -> None:
        raise ClientDisconnect

    @app.get("/disconnects", dependencies=[Depends(abandon_request)])
    def disconnects() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


class TestRequestLoggingMiddleware:
    def test_every_request_gets_one_request_line_with_the_status_the_client_saw(self) -> None:
        # Guards the regression where a raising dependency leaves no request line, which makes a
        # status-code aggregation over these logs read a total outage as zero traffic.
        client = _middleware_test_client()

        with capture_logs() as logs:
            assert client.get("/ok").status_code == 200
            assert client.get("/raises").status_code == 500

        assert [(log["path"], log["status_code"]) for log in logs if log["event"] == "request"] == [
            ("/ok", 200),
            ("/raises", 500),
        ]

    def test_unhandled_exception_is_logged_at_error_level_with_its_traceback(self) -> None:
        client = _middleware_test_client()

        with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs:
            client.get("/raises")

        errors = [log for log in logs if log["event"] == "unhandled_exception"]
        assert len(errors) == 1
        assert errors[0]["log_level"] == "error"
        assert errors[0]["method"] == "GET"
        assert errors[0]["path"] == "/raises"
        assert errors[0]["error_type"] == "RuntimeError"
        assert "permission denied for table posthog_team" in errors[0]["exception"]

        request_lines = [log for log in logs if log["event"] == "request"]
        assert errors[0]["request_id"] == request_lines[0]["request_id"]

    def test_client_disconnect_logs_neither_an_error_nor_a_status(self) -> None:
        # ClientDisconnect is a plain Exception, so a client aborting mid-body would otherwise be
        # reported as a 500 it never saw, and every abort would raise an error-level event.
        client = _middleware_test_client()

        with capture_logs() as logs:
            client.get("/disconnects")

        assert [log for log in logs if log["event"] == "unhandled_exception"] == []
        assert [log for log in logs if log["event"] == "request"] == []
