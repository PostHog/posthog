"""Seed $pageview events with realistic $current_url values for the uptime URL-suggestion feature.

The events are written directly to ClickHouse via the `clickhouse_events_json` Kafka topic,
bypassing the plugin server / ingestion pipeline. Useful when the local ingestion stack is
not running but Kafka + ClickHouse are.
"""

import uuid
import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

from posthog.models.event.util import create_event
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.models.team.team import Team

# Hosts paired with realistic paths and a weight that controls relative frequency.
# Mix of real pingable hosts, a few subdomains, and a couple of unreachable ones — the
# unreachable ones are intentional so the suggestion feature has to filter / rank.
HOSTS: list[tuple[str, list[str], int]] = [
    ("https://posthog.com", ["/", "/pricing", "/docs", "/blog", "/about", "/customers", "/why"], 14),
    ("https://app.posthog.com", ["/", "/dashboard", "/insights", "/replay", "/feature_flags", "/cohorts"], 10),
    ("https://us.posthog.com", ["/", "/project/1", "/project/2"], 6),
    ("https://eu.posthog.com", ["/", "/project/1"], 3),
    ("https://github.com", ["/", "/posthog/posthog", "/posthog/posthog/issues"], 8),
    ("https://news.ycombinator.com", ["/", "/news", "/newest"], 4),
    ("https://stripe.com", ["/", "/pricing", "/docs/api"], 5),
    ("https://vercel.com", ["/", "/docs", "/pricing"], 3),
    ("https://google.com", ["/", "/search"], 9),
    ("https://twitter.com", ["/", "/posthog", "/home"], 4),
    ("https://linkedin.com", ["/", "/feed", "/in/some-user"], 3),
    ("https://reddit.com", ["/", "/r/programming", "/r/webdev"], 4),
    ("https://docs.python.org", ["/3/library/json.html", "/3/tutorial/index.html"], 2),
    ("https://example.com", ["/", "/login", "/signup"], 5),
    ("https://acme-corp.io", ["/", "/products", "/contact"], 3),
    ("http://my-internal-app.local", ["/", "/admin"], 1),
    ("http://localhost:3000", ["/", "/dashboard"], 1),
]

QUERY_STRINGS = ["", "", "", "", "?utm_source=newsletter", "?utm_source=twitter&utm_medium=social", "?ref=hn"]

BROWSERS = ["Chrome", "Firefox", "Safari", "Edge"]
OS_NAMES = ["Mac OS X", "Windows", "iOS", "Android", "Linux"]


class Command(BaseCommand):
    help = "Seed $pageview events with varied $current_url values for the uptime URL suggester."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to seed events into")
        parser.add_argument("--events", type=int, default=2000, help="Total number of $pageview events to create")
        parser.add_argument(
            "--persons", type=int, default=25, help="Number of distinct persons to spread events across"
        )
        parser.add_argument("--days", type=int, default=30, help="Spread events across the last N days")
        parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed for deterministic output")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        n_events: int = options["events"]
        n_persons: int = options["persons"]
        days: int = options["days"]
        rng_seed: int | None = options["seed"]

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} does not exist")

        rng = random.Random(rng_seed)

        self.stdout.write(f"Seeding {n_events} $pageview events across {n_persons} persons into team {team_id}...")

        persons = self._create_persons(team_id, n_persons, rng)
        self.stdout.write(f"  Created {len(persons)} persons")

        weighted_hosts = [host for host in HOSTS for _ in range(host[2])]

        now = datetime.now(tz=ZoneInfo("UTC"))
        window_start = now - timedelta(days=days)
        window_seconds = int((now - window_start).total_seconds())

        for i in range(n_events):
            person_uuid, distinct_id = rng.choice(persons)
            host, paths, _weight = rng.choice(weighted_hosts)
            path = rng.choice(paths)
            query = rng.choice(QUERY_STRINGS)
            current_url = f"{host}{path}{query}"
            host_only = host.split("://", 1)[1]

            timestamp = window_start + timedelta(seconds=rng.randint(0, window_seconds))

            properties = {
                "$current_url": current_url,
                "$host": host_only,
                "$pathname": path,
                "$browser": rng.choice(BROWSERS),
                "$os": rng.choice(OS_NAMES),
                "$lib": "web",
            }

            create_event(
                event_uuid=uuid.uuid4(),
                event="$pageview",
                team=team,
                distinct_id=distinct_id,
                timestamp=timestamp,
                properties=properties,
                person_id=person_uuid,
                person_properties={"email": f"user-{distinct_id}@example.com"},
                person_created_at=window_start,
            )

            if (i + 1) % 500 == 0:
                self.stdout.write(f"  Inserted {i + 1}/{n_events} events")

        self.stdout.write(self.style.SUCCESS(f"Done. Inserted {n_events} events into team {team_id}."))
        self.stdout.write(
            "Allow a few seconds for ClickHouse to consume from Kafka, then verify with a HogQL query like:"
        )
        self.stdout.write("  SELECT properties.$host AS host, count() FROM events")
        self.stdout.write("  WHERE event = '$pageview' GROUP BY host ORDER BY count() DESC")

    def _create_persons(self, team_id: int, n: int, rng: random.Random) -> list[tuple[str, str]]:
        persons: list[tuple[str, str]] = []
        for i in range(n):
            person_uuid = str(uuid.uuid4())
            distinct_id = f"seed-uptime-{i:03d}-{rng.randint(1000, 9999)}"
            create_person(
                team_id=team_id,
                version=0,
                uuid=person_uuid,
                properties={"email": f"user-{distinct_id}@example.com", "$seed_source": "seed_uptime_urls"},
            )
            create_person_distinct_id(team_id=team_id, distinct_id=distinct_id, person_id=person_uuid)
            persons.append((person_uuid, distinct_id))
        return persons
