from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from asgiref.sync import async_to_sync

from posthog.storage import object_storage
from posthog.temporal.common.client import sync_connect

from products.replay_vision.backend.benchmark.layout import BenchmarkLayout
from products.replay_vision.backend.temporal.benchmark_types import BuildBenchmarkInputs
from products.replay_vision.backend.temporal.constants import BUILD_BENCHMARK_WORKFLOW_NAME


class Command(BaseCommand):
    help = "Build a frozen Replay Vision labeling benchmark version from the labeling suite's labels"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("version", help="Version name, for example v1. A built version is never rewritten.")
        parser.add_argument("--recording-limit", type=int, default=None, help="Cap the version to this many recordings")
        parser.add_argument("--max-concurrent-renders", type=int, default=4)

    def handle(self, *args: object, **options: object) -> None:
        inputs = BuildBenchmarkInputs(
            version=str(options["version"]),
            recording_limit=options["recording_limit"],
            max_concurrent_renders=options["max_concurrent_renders"],
        )
        layout = BenchmarkLayout(inputs.version)
        if layout.bucket and object_storage.head_object(layout.manifest_key, bucket=layout.bucket):
            raise CommandError(f"Benchmark version {inputs.version} is already built. Pick a new version name.")
        workflow_id = f"{BUILD_BENCHMARK_WORKFLOW_NAME}-{inputs.version}"
        client = sync_connect()
        async_to_sync(client.start_workflow)(  # type: ignore[misc]
            BUILD_BENCHMARK_WORKFLOW_NAME,  # type: ignore[arg-type]
            inputs,  # type: ignore[arg-type]
            id=workflow_id,
            task_queue=settings.REPLAY_VISION_TASK_QUEUE,
        )
        self.stdout.write(f"Started {workflow_id}")
