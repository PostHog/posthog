import asyncio
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from prometheus_client import start_http_server

from posthog.temporal.common.health_server import HealthCheckServer
from posthog.temporal.common.liveness_tracker import LivenessTracker

from products.replay_vision.backend.watch_rank_consumer import WatchRankConsumer


class Command(BaseCommand):
    help = "Rank Replay Vision observations for the highlight feed from the embedding worker's results topic"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--health-port", type=int, default=8090, help="Port for /healthz and /readyz")
        parser.add_argument(
            "--health-max-idle-seconds",
            type=float,
            default=120.0,
            help="Seconds without a consume loop heartbeat before the health checks fail",
        )
        parser.add_argument("--metrics-port", type=int, default=8001, help="Port for Prometheus metrics")

    def handle(self, *args: Any, **options: Any) -> None:
        start_http_server(options["metrics_port"])
        asyncio.run(self._run(options["health_port"], options["health_max_idle_seconds"]))

    async def _run(self, health_port: int, max_idle_seconds: float) -> None:
        liveness = LivenessTracker()
        health = HealthCheckServer(health_port, liveness, max_idle_seconds=max_idle_seconds)
        await health.start()
        try:
            await WatchRankConsumer(liveness).run()
        finally:
            await health.stop()
