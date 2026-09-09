from __future__ import annotations

import os
import sys
import json
import socket
import asyncio
import logging
import secrets
import argparse
import subprocess
import logging.config
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4


def build_skills() -> None:
    from unittest.mock import patch

    from posthog.models import Organization, Team

    from products.posthog_ai.eval_harness.harness.services import build_local_skills

    organization = Organization.objects.create(name=f"Synthetic AI E2E build {uuid4().hex}")
    try:
        team = Team.objects.create(
            id=secrets.randbelow(1_000_000_000) + 1_000_000_000,
            organization=organization,
            name="Synthetic skill rendering project",
        )
        with patch("products.posthog_ai.scripts.hogql_example._cached_team", team):
            build_local_skills(set_bind_mount_env=True)
    finally:
        organization.delete()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AI browser tests with real services and replayed model responses")
    parser.add_argument(
        "--attach",
        action="store_true",
        help="Reuse provisioned infrastructure; still create and remove an isolated application database",
    )
    parser.add_argument("--retries", type=int)
    parser.add_argument("--repeat-each", type=int, default=1)
    parser.add_argument("--grep")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--image-cache", type=Path)
    args = parser.parse_args()
    if args.repeat_each < 1 or (args.retries is not None and args.retries < 0):
        parser.error("Repetitions must be positive and retries cannot be negative")
    root = Path(__file__).resolve().parents[4]
    output = root / "products/posthog_ai/frontend/e2e/artifacts" / uuid4().hex
    output.mkdir(parents=True)
    logging.basicConfig(
        level=logging.INFO, handlers=[logging.FileHandler(output / "services.log"), logging.StreamHandler()]
    )
    for key in list(os.environ):
        if any(
            key.startswith(prefix)
            for prefix in ("ANTHROPIC_", "OPENAI_", "LLM_GATEWAY_", "AI_GATEWAY_", "SANDBOX_AI_GATEWAY_", "BRAINTRUST_")
        ):
            del os.environ[key]
    os.environ.update(
        {
            "SANDBOX_PROVIDER": "docker",
            "E2E_TESTING": "1",
            "SELF_CAPTURE": "0",
            "CLOUD_DEPLOYMENT": "E2E",
            "ANTHROPIC_API_KEY": "sk-ant-synthetic-ai-e2e",
            "OPENAI_API_KEY": "sk-synthetic-ai-e2e",
            "LOCAL_POSTHOG_CODE_MONOREPO_ROOT": str(root / "products/desktop"),
            "OTEL_TRACES_EXPORTER": "none",
            "OPT_OUT_CAPTURE": "1",
            "DJANGO_LOG_LEVEL": "INFO",
            "POSTHOG_ANALYTICS_API_KEY": "",
            "POSTHOG_ANALYTICS_HOST": "",
        }
    )
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    os.environ["SANDBOX_JWT_PRIVATE_KEY"] = signing_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()

    from products.posthog_ai.eval_harness.harness.django_env import NullDbBlocker, setup_django

    setup_django()

    from django.conf import settings
    from django.test import override_settings

    from products.posthog_ai.eval_harness.harness.live_server import EvalLiveServer
    from products.posthog_ai.eval_harness.harness.ports import PERSONHOG_ROUTER_PORT
    from products.posthog_ai.eval_harness.harness.services import (
        ensure_personhog_binaries,
        start_personhog,
    )
    from products.posthog_ai.eval_harness.harness.temporal_env import start_temporal_env, temporal_client_target

    from .controller import Controller
    from .database import isolated_database
    from .egress import restrict_egress
    from .flags import flag_values, install_flags
    from .hooks import install_hooks
    from .image import build_image
    from .metrics import ResourceMonitor
    from .processes import Processes

    log_config = deepcopy(settings.LOGGING)
    log_config["disable_existing_loggers"] = False
    log_config["handlers"]["ai_e2e"] = {
        "class": "logging.FileHandler",
        "filename": str(output / "services.log"),
        "formatter": "json",
    }
    log_config["root"]["handlers"].append("ai_e2e")
    log_config["root"]["level"] = "INFO"
    for logger_config in log_config["loggers"].values():
        if not logger_config.get("propagate", True):
            logger_config.setdefault("handlers", []).append("ai_e2e")

    monitor = ResourceMonitor()
    try:
        with ExitStack() as stack:
            processes = Processes(stack, root, output)
            if not args.attach:
                subprocess.run(["hogli", "services:ready", "-y"], cwd=root, check=True)
            with monitor.stage("database"):
                stack.enter_context(isolated_database(root))
            if not args.attach:
                from posthog.conftest import _django_db_setup

                stack.enter_context(contextmanager(_django_db_setup)(True, NullDbBlocker()))
                ensure_personhog_binaries()
                stack.callback(start_personhog())
            controller = Controller(output)
            stack.callback(controller.close)
            install_flags(stack, output, controller.record_error)
            with socket.socket() as proxy_socket, socket.socket() as mcp_socket:
                proxy_socket.bind(("127.0.0.1", 0))
                mcp_socket.bind(("127.0.0.1", 0))
                proxy_port = proxy_socket.getsockname()[1]
                mcp_port = mcp_socket.getsockname()[1]
            proxy_url = f"http://127.0.0.1:{proxy_port}"
            os.environ["ANTHROPIC_BASE_URL"] = f"{controller.url}/title"
            gateway = controller.url.replace("127.0.0.1", "host.docker.internal")
            overrides = {
                "DEBUG": True,
                "LOGGING": log_config,
                "TEST": False,
                "SERVER_GATEWAY_INTERFACE": "ASGI",
                "JS_URL": "",
                "ALLOWED_HOSTS": ["*"],
                "SECURE_SSL_REDIRECT": False,
                "SESSION_COOKIE_SECURE": False,
                "CSRF_COOKIE_SECURE": False,
                "SANDBOX_LLM_GATEWAY_URL": gateway,
                "SANDBOX_AI_GATEWAY_URL": gateway,
                "SANDBOX_AI_GATEWAY_PRODUCTS": "",
                "SANDBOX_AI_GATEWAY_MINT_KEY": "",
                "LLM_GATEWAY_URL": controller.url,
                "LLM_GATEWAY_API_KEY": "synthetic-gateway-key",
                "AI_GATEWAY_URL": f"{controller.url}/v1",
                "AI_GATEWAY_API_KEY": "synthetic-gateway-key",
                "TASKS_TASK_QUEUE": f"ai-e2e-{uuid4().hex}",
                "TASKS_REDIS_URL": settings.REDIS_URL,
                "TASKS_AGENT_PROXY_INGEST_URL": proxy_url.replace("127.0.0.1", "host.docker.internal"),
                "TASKS_AGENT_PROXY_PUBLIC_URL": proxy_url,
                "TASKS_AGENT_PROXY_INTERNAL_URL": proxy_url,
                "AGENT_PROXY_CALLBACK_SECRET": controller.token,
                "CACHES": {
                    alias: {
                        "BACKEND": "django_redis.cache.RedisCache",
                        "LOCATION": settings.REDIS_URL,
                        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
                        "KEY_PREFIX": f"ai-e2e-{controller.token}-{alias}",
                    }
                    for alias in settings.CACHES
                },
            }
            if args.attach:
                overrides["CLICKHOUSE_DATABASE"] = os.getenv("CLICKHOUSE_DATABASE", settings.CLICKHOUSE_DATABASE)
            if not args.attach:
                temporal_loop = asyncio.new_event_loop()
                temporal = temporal_loop.run_until_complete(start_temporal_env())
                stack.callback(temporal_loop.close)
                stack.callback(lambda: temporal_loop.run_until_complete(temporal.shutdown()))
                host, port = temporal_client_target(temporal)
                overrides.update(
                    TEMPORAL_HOST=host,
                    TEMPORAL_PORT=port,
                    TEMPORAL_CLIENT_CERT=None,
                    TEMPORAL_CLIENT_KEY=None,
                    PERSONHOG_ADDR=f"127.0.0.1:{PERSONHOG_ROUTER_PORT}",
                )
            stack.enter_context(override_settings(**overrides))
            logging.config.dictConfig(log_config)
            from posthog.redis import TEST_clear_clients

            TEST_clear_clients()
            from django.core.cache import caches

            from django_redis.cache import RedisCache

            def clear_owned_caches() -> None:
                for alias in settings.CACHES:
                    cache = caches[alias]
                    assert isinstance(cache, RedisCache)
                    cache.delete_pattern("*")

            stack.callback(clear_owned_caches)
            from posthog.clickhouse.client.connection import make_ch_pool

            make_ch_pool.cache_clear()
            build_skills()
            from products.tasks.backend.logic.services.docker_sandbox import (
                DEFAULT_IMAGE_NAME,
                DockerSandbox,
                _base_dockerfile_path,
            )

            archive = args.image_cache / "sandbox.tar" if args.image_cache else None
            if archive and archive.exists():
                subprocess.run(["docker", "load", "--input", str(archive)], check=True)
            DockerSandbox._build_image_if_needed(DEFAULT_IMAGE_NAME, _base_dockerfile_path())
            with monitor.stage("sandbox_image"):
                image_id = build_image(root, output)
            if archive and not archive.exists():
                archive.parent.mkdir(parents=True, exist_ok=True)
                provenance = json.loads((output / "image-provenance.json").read_text())
                subprocess.run(
                    ["docker", "save", "--output", str(archive), DEFAULT_IMAGE_NAME, provenance["tag"]], check=True
                )
            if args.prepare_only:
                return 0
            if not (root / "frontend/dist/preload-manifest.json").exists():
                subprocess.run(["bin/turbo", "--filter=@posthog/frontend", "prepare"], cwd=root, check=True)
                subprocess.run(["pnpm", "--filter=@posthog/frontend", "build:products"], cwd=root, check=True)
                subprocess.run(["pnpm", "--filter=@posthog/frontend", "build"], cwd=root, check=True)
            install_hooks(stack, controller, image_id)
            server = EvalLiveServer(port=0)
            stack.callback(server.stop)
            stack.enter_context(
                override_settings(
                    SANDBOX_API_URL=server.url.replace("127.0.0.1", "host.docker.internal"),
                    SITE_URL=server.url,
                    SANDBOX_MCP_URL=f"http://host.docker.internal:{mcp_port}/mcp",
                    POSTHOG_CONNECT_BASE_URL_DEV=server.url,
                    POSTHOG_CONNECT_OAUTH_CLIENT_ID_DEV="synthetic-ai-e2e-connection",
                    POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_DEV=controller.token,
                )
            )
            with monitor.stage("agent_proxy_build"):
                subprocess.run(["pnpm", "--filter=@posthog/agent-proxy", "build"], cwd=root, check=True)
            with monitor.stage("mcp_build"):
                subprocess.run(["pnpm", "--filter=@posthog/mcp", "build:hono"], cwd=root, check=True)
            with monitor.stage("agent_proxy_startup"):
                processes.start(
                    "agent-proxy",
                    ["node", "services/agent-proxy/dist/agent-proxy-server.mjs"],
                    {
                        **os.environ,
                        "NODE_ENV": "production",
                        "HOST": "0.0.0.0",
                        "PORT": str(proxy_port),
                        "TASKS_REDIS_URL": settings.REDIS_URL,
                        "SANDBOX_JWT_PUBLIC_KEY": signing_key.public_key().public_bytes(
                            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
                        ).decode(),
                        "SANDBOX_JWT_PUBLIC_KEY_SECONDARY": "",
                        "AGENT_PROXY_DJANGO_CALLBACK_URL": server.url,
                        "AGENT_PROXY_CALLBACK_SECRET": controller.token,
                        "TASKS_AGENT_PROXY_CORS_ORIGINS": server.url,
                        "AGENT_PROXY_LOG_LEVEL": "info",
                        "SHUTDOWN_GRACE_MS": "1000",
                        "SHUTDOWN_PRESTOP_DELAY_MS": "0",
                    },
                )
                processes.ready_http(f"{proxy_url}/_readyz")
            with monitor.stage("mcp_startup"):
                processes.start(
                    "mcp",
                    ["node", "services/mcp/dist/hono-server.mjs"],
                    {
                        **os.environ,
                        "NODE_ENV": "development",
                        "HOST": "0.0.0.0",
                        "PORT": str(mcp_port),
                        "REDIS_URL": settings.REDIS_URL,
                        "POSTHOG_API_BASE_URL": server.url,
                        "MCP_APPS_BASE_URL": f"http://127.0.0.1:{mcp_port}",
                        "POSTHOG_MCP_APPS_ANALYTICS_BASE_URL": server.url,
                        "FEATURE_FLAG_OVERRIDES": json.dumps(flag_values("mcp")),
                    },
                )
                processes.ready_http(f"http://127.0.0.1:{mcp_port}/readyz")
            dispatcher_output = output / "dispatcher"
            dispatcher_output.mkdir()
            with monitor.stage("dispatcher_startup"):
                processes.start(
                    "dispatcher",
                    [sys.executable, "-m", "products.posthog_ai.frontend.e2e.dispatcher"],
                    dict(os.environ),
                    configuration=json.dumps(
                        {
                            "controller": controller.url,
                            "token": controller.token,
                            "output": str(dispatcher_output),
                            "settings": {key: value for key, value in overrides.items() if key != "LOGGING"},
                        }
                    ).encode(),
                )
                processes.ready(lambda: (dispatcher_output / "dispatcher-ready").exists())
            restrict_egress(stack, controller)
            stack.callback(controller.finish_active_attempt)
            env = {
                **os.environ,
                "AI_E2E_CONTROLLER": controller.url,
                "AI_E2E_TOKEN": controller.token,
                "AI_E2E_BASE_URL": server.url,
                "AI_E2E_OUTPUT": str(output),
                "AI_E2E_PROXY_URL": proxy_url,
            }
            command = [
                "pnpm",
                "--filter=@posthog/playwright",
                "exec",
                "playwright",
                "test",
                "--config",
                str(Path(__file__).with_name("playwright.config.ts")),
                "--workers=1",
                f"--repeat-each={args.repeat_each}",
            ]
            if args.retries is not None:
                command.append(f"--retries={args.retries}")
            if args.grep:
                command.extend(["--grep", args.grep])
            with monitor.stage("browser"):
                result = processes.run_browser(command, env)
        return result or int(bool(controller.errors))
    finally:
        if "controller" in locals():
            (output / "controller-errors.json").write_text(json.dumps(controller.errors, indent=2))
        (output / "metrics.json").write_text(json.dumps(monitor.finish(), indent=2))
        sys.stdout.write(f"AI E2E artifacts: {output}\n")


if __name__ == "__main__":
    sys.exit(main())
