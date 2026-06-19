from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.start_agent_server import (
    StartAgentServerInput,
    start_agent_server,
)


def _context(*, sandbox_event_ingest_enabled: bool = False) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=None,
        repository=None,
        distinct_id="distinct-id",
        sandbox_event_ingest_enabled=sandbox_event_ingest_enabled,
    )


async def test_start_agent_server_uses_captured_sandbox_event_ingest_flag(mocker) -> None:
    context = _context(sandbox_event_ingest_enabled=True)
    sandbox = mocker.Mock()
    sandbox.execute.return_value.stdout = ""
    sandbox.execute.return_value.stderr = ""
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
        return_value=sandbox,
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Task.objects.select_related"
    ).return_value.get.return_value = mocker.Mock(created_by_id=None)
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.create_oauth_access_token",
        return_value="oauth-token",
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.get_sandbox_ph_mcp_configs",
        return_value=[],
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.TaskRun.objects.get",
        return_value=mocker.Mock(),
    )
    create_event_ingest_token = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.create_sandbox_event_ingest_token",
        return_value="event-ingest-token",
    )

    result = await start_agent_server(
        StartAgentServerInput(
            context=context,
            sandbox_id="sandbox-id",
            sandbox_url="https://sandbox.example",
            sandbox_connect_token="connect-token",
        )
    )

    assert result.sandbox_url == "https://sandbox.example"
    assert result.connect_token == "connect-token"
    create_event_ingest_token.assert_called_once()
    sandbox.start_agent_server.assert_called_once()
    assert sandbox.start_agent_server.call_args.kwargs["event_ingest_token"] == "event-ingest-token"
