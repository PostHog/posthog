from __future__ import annotations

import os
import sys
import json
import asyncio
import logging
import argparse
import subprocess
import logging.config
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from uuid import uuid4


def build_skills() -> None:
    from unittest.mock import patch

    from posthog.models import Organization, Team

    from products.posthog_ai.eval_harness.harness.services import build_local_skills

    organization = Organization.objects.create(name=f"Synthetic AI E2E build {uuid4().hex}")
    try:
        team = Team.objects.create(organization=organization, name="Synthetic skill rendering project")
        with patch("products.posthog_ai.scripts.hogql_example._cached_team", team):
            build_local_skills(set_bind_mount_env=True)
    finally:
        organization.delete()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AI browser tests with real services and replayed model responses")
    parser.add_argument(
        "--attach",
        action="store_true",
        help="Use provisioned databases and Temporal; never start or stop those services",
    )
    parser.add_argument("--retries", type=int)
    parser.add_argument("--repeat-each", type=int, default=1)
    parser.add_argument("--grep")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--image-cache", type=Path)
    args = parser.parse_args()
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

    from products.posthog_ai.eval_harness.harness.django_env import EvalDatabase, setup_django

    setup_django()

    from django.conf import settings
    from django.test import override_settings

    from products.posthog_ai.eval_harness.harness.live_server import EvalLiveServer
    from products.posthog_ai.eval_harness.harness.ports import PERSONHOG_ROUTER_PORT
    from products.posthog_ai.eval_harness.harness.services import (
        ensure_personhog_binaries,
        start_mcp_server,
        start_personhog,
    )
    from products.posthog_ai.eval_harness.harness.temporal_env import start_temporal_env, temporal_client_target

    from .controller import Controller
    from .egress import restrict_egress
    from .hooks import install_hooks
    from .image import build_image
    from .metrics import ResourceMonitor

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
            if not args.attach:
                subprocess.run(["hogli", "services:ready", "-y"], cwd=root, check=True)
                database = EvalDatabase(keepdb=True)
                database.setup()
                stack.callback(database.teardown)
                ensure_personhog_binaries()
                stack.callback(start_personhog())
            controller = Controller(output)
            stack.callback(controller.close)
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
                "AGENT_PROXY_BASE_URL": None,
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
                    SANDBOX_MCP_URL="http://host.docker.internal:18787/mcp",
                    POSTHOG_CONNECT_BASE_URL_DEV=server.url,
                    POSTHOG_CONNECT_OAUTH_CLIENT_ID_DEV="synthetic-ai-e2e-connection",
                    POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_DEV=controller.token,
                )
            )
            stack.callback(start_mcp_server(server.url, feature_flags={"posthog-connect": True}))
            restrict_egress(stack, controller)
            stack.callback(controller.finish_active_attempt)
            env = {
                **os.environ,
                "AI_E2E_CONTROLLER": controller.url,
                "AI_E2E_TOKEN": controller.token,
                "AI_E2E_BASE_URL": server.url,
                "AI_E2E_OUTPUT": str(output),
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
            result = subprocess.run(command, cwd=root, env=env)
            return result.returncode or int(bool(controller.errors))
    finally:
        if "controller" in locals():
            (output / "controller-errors.json").write_text(json.dumps(controller.errors, indent=2))
        (output / "metrics.json").write_text(json.dumps(monitor.finish(), indent=2))
        sys.stdout.write(f"AI E2E artifacts: {output}\n")


if __name__ == "__main__":
    sys.exit(main())
