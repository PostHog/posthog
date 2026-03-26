from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError

from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_HOGBOT_SIGNALS_TOPIC
from posthog.models import Team

EXAMPLE_SIGNAL_COUNT = 10
SIGNAL_EXAMPLE_CONTENT = """
New error tracking issue created - this particular exception was observed for the first time:
ClientError: An error occurred (RequestTimeTooSkewed) when calling the GetObject operation: The difference between the request time and the server's time is too large.

```
ClientError: An error occurred (RequestTimeTooSkewed) when calling the GetObject operation: The difference between the request time and the server's time is too large.
read_bytes in posthog/storage/object_storage.py line 220
_api_call in botocore/client.py line 602
wrapper in botocore/context.py line 123
_make_api_call in botocore/client.py line 1078

```
""".strip()


def _build_signal_payloads(*, team_id: int, description: str) -> list[dict]:
    content = description.strip()

    return [
        {
            "signal_id": str(uuid4()),
            "team_id": team_id,
            "source_product": "error_tracking",
            "source_type": "issue_created",
            "source_id": f"error-tracking-issue-{index + 1}",
            "description": content,
            "weight": 0.5,
            "extra": {"fingerprint": f"request-time-too-skewed-{index + 1}"},
        }
        for index in range(EXAMPLE_SIGNAL_COUNT)
    ]


class Command(BaseCommand):
    help = "Emit 10 example error tracking signals directly to the hogbot Kafka topic"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to emit signals for")

    def handle(self, *args, **options):
        team_id = options["team_id"]

        if not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"Team {team_id} not found")

        producer = KafkaProducer()
        payloads = _build_signal_payloads(team_id=team_id, description=SIGNAL_EXAMPLE_CONTENT)

        for payload in payloads:
            producer.produce(
                topic=KAFKA_HOGBOT_SIGNALS_TOPIC,
                data=payload,
                key=str(team_id),
            )

        producer.flush()

        self.stdout.write(
            self.style.SUCCESS(
                f"Emitted {len(payloads)} example signals to {KAFKA_HOGBOT_SIGNALS_TOPIC} for team {team_id}"
            )
        )
