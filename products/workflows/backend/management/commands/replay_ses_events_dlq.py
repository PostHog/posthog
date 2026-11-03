import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.workflows.backend.services.ses_events_dlq import (
    ReplayOptions,
    configured_queues,
    find_queue,
    replay_queue,
    sqs_client,
)


class Command(BaseCommand):
    help = (
        "Post SES events that the CDP webhook failed to process again, from the dead-letter queues in "
        "SES_EVENTS_DLQ_URLS. A message leaves its queue only after the webhook accepts it."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--queue", help="Queue name to replay. Omit it to replay every configured queue.")
        parser.add_argument("--dry-run", action="store_true", help="Read and count messages without posting them")
        parser.add_argument("--limit", type=int, default=1000, help="Most messages to take from each queue")
        parser.add_argument("--max-per-second", type=float, default=20.0, help="Most webhook posts per second")

    def handle(self, *args: Any, **options: Any) -> None:
        queues = configured_queues()
        if options["queue"]:
            queue = find_queue(options["queue"])
            if queue is None:
                raise CommandError(f"No queue named {options['queue']}. Configured: {[q.name for q in queues]}")
            queues = [queue]
        if not queues:
            raise CommandError("SES_EVENTS_DLQ_URLS is empty, so there is no queue to replay.")

        try:
            replay_options = ReplayOptions(
                dry_run=options["dry_run"], limit=options["limit"], max_per_second=options["max_per_second"]
            )
        except ValueError as error:
            raise CommandError(str(error))
        for queue in queues:
            report = replay_queue(
                queue, replay_options, sqs=sqs_client(queue), triggered_by="replay_ses_events_dlq command"
            )
            self.stdout.write(json.dumps(report.to_dict(), indent=2))
