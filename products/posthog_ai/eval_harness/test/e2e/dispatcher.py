from __future__ import annotations

import sys
import json
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from pathlib import Path
from typing import cast

from unittest.mock import patch

import requests
from pydantic import JsonValue

from .flags import install_flags
from .replay import object_value


def main() -> None:
    configuration = object_value(json.load(sys.stdin))
    url = str(configuration["controller"])
    token = str(configuration["token"])

    def control(path: str, body: dict[str, JsonValue]) -> dict[str, JsonValue]:
        response = requests.post(
            f"{url}/control/{path}", json=body, headers={"Authorization": f"Bearer {token}"}, timeout=100
        )
        response.raise_for_status()
        return object_value(response.json())

    from products.posthog_ai.eval_harness.harness.django_env import setup_django

    setup_django()

    from django.core.management import call_command
    from django.test import override_settings

    from temporalio.client import Client

    from products.tasks.backend.temporal.process_task.workflow import ProcessTaskInput

    def trace_registration[**P, R](original: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        async def registered(*args: P.args, **kwargs: P.kwargs) -> R:
            workflow = args[1] if len(args) > 1 else kwargs.get("workflow")
            if workflow != "process-task":
                raise ValueError("AI E2E dispatcher attempted an unexpected workflow")
            argument = args[2] if len(args) > 2 else kwargs.get("arg")
            body: dict[str, JsonValue] = {
                "run_id": cast(ProcessTaskInput, argument).run_id,
                "workflow_id": str(kwargs["id"]),
            }
            registration = await asyncio.to_thread(control, "dispatcher/register", body)
            path = f"{registration['attempt_id']}/dispatcher"
            try:
                handle = await original(*args, **kwargs)
            except Exception as error:
                await asyncio.to_thread(control, f"{path}/failed", {**body, "error": str(error)})
                raise
            await asyncio.to_thread(control, f"{path}/registered", body)
            return handle

        return registered

    with ExitStack() as stack:
        stack.enter_context(override_settings(**object_value(configuration["settings"])))

        def record_error(error: str) -> None:
            control("dispatcher/error", {"error": error})

        install_flags(stack, Path(str(configuration["output"])), record_error)
        stack.enter_context(patch.object(Client, "start_workflow", trace_registration(Client.start_workflow)))
        call_command("run_task_workflow_dispatcher", metrics_port=0, health_directory=str(configuration["output"]))


if __name__ == "__main__":
    main()
