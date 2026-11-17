import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandParser

from products.tasks.backend.logic.services.agent_egress_probe_runner import (
    AgentEgressProbeConfig,
    AgentEgressProbeRunner,
)


class Command(BaseCommand):
    help = "Exercise a development Tasks VM through its isolated egress relay"
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--config", type=Path, required=True)

    def handle(self, *args: str, **options: object) -> None:
        path = options["config"]
        if not isinstance(path, Path):
            raise ValueError("A probe configuration file is required")
        config = AgentEgressProbeConfig.model_validate_json(path.read_bytes())
        AgentEgressProbeRunner(config, report=lambda event: self.stdout.write(json.dumps(event))).run()
