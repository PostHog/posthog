from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from typing import cast

from unittest.mock import patch

from .controller import Controller


def install_hooks(stack: ExitStack, controller: Controller, image_id: str) -> None:
    from django.db import transaction

    from pydantic import JsonValue
    from requests import Response
    from temporalio.client import WorkflowHandle
    from temporalio.service import RPCError, RPCStatusCode

    from posthog.temporal.oauth import PosthogMcpScopes

    from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
    from products.tasks.backend.presentation.views.api import TaskRunViewSet
    from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
        TaskProcessingContext,
    )
    from products.tasks.backend.temporal.process_task.activities.start_agent_server import (
        _LaunchParams,
        _prepare_launch,
    )

    proxy = TaskRunViewSet._proxy_command_to_agent_server

    def prepared(ctx: TaskProcessingContext, scopes: PosthogMcpScopes, sandbox_id: str) -> _LaunchParams:
        params = _prepare_launch(ctx, scopes, sandbox_id)
        attempt = controller.attempt
        if attempt is None or ctx.run_id != attempt.run_id:
            raise ValueError("Agent launch belongs to another attempt")
        attempt.agent_configuration = {
            "event_ingest_url": params.event_ingest_url,
            "event_ingest_keep_stream_open": params.event_ingest_keep_stream_open,
        }
        return params

    def trace_signal[**P, R](original: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        async def signalled(*args: P.args, **kwargs: P.kwargs) -> R:
            handle = cast(WorkflowHandle, args[0])
            attempt = controller.attempt
            try:
                result = await original(*args, **kwargs)
            except RPCError as error:
                if attempt and handle.id == attempt.workflow_id and error.status == RPCStatusCode.NOT_FOUND:
                    attempt.faults["registration"].record("temporal_not_found", workflow_id=handle.id)
                    attempt.signal_not_found.set()
                raise
            if attempt and handle.id == attempt.workflow_id:
                attempt.faults["registration"].record("signal_accepted", workflow_id=handle.id)
                attempt.signal_accepted.set()
            return result

        return signalled

    def proxied(
        *,
        sandbox_url: str,
        connection_token: str | None,
        sandbox_connect_token: str | None,
        payload: dict[str, JsonValue],
        sandbox_token_param: str = "_modal_connect_token",
    ) -> Response:
        attempt = controller.attempt
        if attempt and payload.get("method") == "permission_response":
            import jwt

            from products.tasks.backend.logic.services.connection_token import get_sandbox_jwt_public_key

            if connection_token is None:
                raise ValueError("Approval command is missing its signed connection token")
            claims = jwt.decode(
                connection_token, get_sandbox_jwt_public_key(), algorithms=["RS256"], options={"verify_aud": False}
            )
            if claims.get("run_id") != attempt.run_id or str(claims.get("team_id")) != str(attempt.team.id):
                raise ValueError("Approval command belongs to another attempt")
            controller.proxy_targets[attempt.id] = sandbox_url
            sandbox_url = f"{controller.url}/proxy/{attempt.id}"
        return proxy(
            sandbox_url=sandbox_url,
            connection_token=connection_token,
            sandbox_connect_token=sandbox_connect_token,
            payload=payload,
            sandbox_token_param=sandbox_token_param,
        )

    stack.enter_context(
        patch("products.tasks.backend.logic.services.workflow_dispatch.execute_after_commit", transaction.on_commit)
    )
    stack.enter_context(patch("ee.billing.billing_manager.BILLING_SERVICE_URL", f"{controller.url}/billing"))
    stack.enter_context(patch.object(WorkflowHandle, "signal", trace_signal(WorkflowHandle.signal)))
    stack.enter_context(patch.object(TaskRunViewSet, "_proxy_command_to_agent_server", staticmethod(proxied)))
    stack.enter_context(patch.object(DockerSandbox, "_ensure_image_exists", return_value=image_id))
    stack.enter_context(
        patch("products.tasks.backend.temporal.process_task.activities.start_agent_server._prepare_launch", prepared)
    )
    stack.enter_context(
        patch(
            "products.tasks.backend.logic.services.code_usage_gate._gateway_usage_url",
            return_value=f"{controller.url}/v1/usage/posthog_code",
        )
    )

    from django.db.models.signals import post_save

    from products.product_analytics.backend.models.insight import Insight

    def insight_saved(sender: type[Insight], instance: Insight, created: bool, **kwargs: object) -> None:
        attempt = controller.attempt
        if (
            attempt
            and not created
            and instance.team_id == attempt.connected_team.id
            and instance.pk == attempt.insight.pk
        ):
            attempt.tool_executions += 1
            attempt.faults["approval"].record("insight_saved", insight_id=instance.pk, name=instance.name)

    post_save.connect(insight_saved, sender=Insight, weak=False)
    stack.callback(post_save.disconnect, insight_saved, sender=Insight)
