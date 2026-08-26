from django.core.management.base import BaseCommand

from products.warehouse_sources.backend.temporal.data_imports.person_property_update_consumer import (
    PersonPropertyUpdateConsumer,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.health import (
    HealthState,
    start_health_server,
)


class Command(BaseCommand):
    help = "Consume warehouse person-property $set intents and send them to capture, rate-limited."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--health-port",
            type=int,
            default=8090,
            help="Port for the liveness/readiness/metrics HTTP server (default: 8090).",
        )
        parser.add_argument(
            "--health-timeout",
            type=float,
            default=120.0,
            help="Seconds without a loop heartbeat before liveness fails (default: 120.0).",
        )

    def handle(self, *args, **options) -> None:
        # Readiness gating is what makes running many replicas safe: k8s only keeps a pod once its
        # loop is heartbeating. The reporter is called each loop turn and during throttle/retry
        # waits so a pod that's merely rate-limited stays live.
        health_state = HealthState(timeout_seconds=options["health_timeout"])
        start_health_server(port=options["health_port"], health_state=health_state)
        PersonPropertyUpdateConsumer().run(health_reporter=health_state.report_healthy)
