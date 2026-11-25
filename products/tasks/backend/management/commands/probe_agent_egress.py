import json
import asyncio
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from posthog.temporal.common.client import async_connect

from products.tasks.backend.logic.services.agent_egress_probe import AgentEgressProbeConfig
from products.tasks.backend.logic.services.agent_egress_probe_runner import AgentEgressProbeRunner
from products.tasks.backend.temporal.agent_egress import AgentEgressProbeWorkflow
from products.tasks.backend.temporal.process_task.activities.agent_egress import AgentEgressProbeInput


class Command(BaseCommand):
    help = "Exercise a development Tasks VM through its isolated egress relay"
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--config", type=Path, required=True)
        parser.add_argument("--temporal", action="store_true")
        parser.add_argument("--task-queue", default=settings.TEMPORAL_TASK_QUEUE)

    async def run_workflow(self, config: AgentEgressProbeConfig, path: Path, task_queue: str) -> None:
        client = await async_connect()
        handle = await client.start_workflow(
            AgentEgressProbeWorkflow.run,
            AgentEgressProbeInput(config_path=str(path.resolve()), team_id=config.team_id, run_id=str(config.run_id)),
            id=f"agent-egress-probe-{config.run_id}",
            task_queue=task_queue,
            execution_timeout=timedelta(minutes=15),
        )
        self.stdout.write(json.dumps({"workflow_id": handle.id, "workflow_run_id": handle.first_execution_run_id}))
        try:
            self.stdout.write(json.dumps({"total_statuses": await handle.result()}))
        except BaseException:
            await asyncio.shield(handle.cancel())
            raise

    def handle(self, *args: str, **options: object) -> None:
        path = options["config"]
        if not isinstance(path, Path):
            raise ValueError("A probe configuration file is required")
        config = AgentEgressProbeConfig.load(path)
        if options["temporal"]:
            config.eligible_run()
            asyncio.run(self.run_workflow(config, path, str(options["task_queue"])))
            return
        AgentEgressProbeRunner(config, report=lambda event: self.stdout.write(json.dumps(event))).run()
