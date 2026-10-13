from typing import Any

from django.core.management.base import BaseCommand

from products.mcp_registry.backend.constants import PROBE_BATCH_SIZE, PROBE_CONCURRENCY
from products.mcp_registry.backend.probe import probe_stalest_servers, probeable_server_count


class Command(BaseCommand):
    help = (
        "Probe every reachable registry server once, stalest first. The scheduled job only "
        "probes a batch a day, so a fresh index would spend weeks with most servers unprobed, "
        "and liveness carries more ranking weight than anything else. Run this after the first "
        "crawl so the ranking reflects which servers actually answer. Bypasses the feature-flag "
        "gate because this command is an explicit human action."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many servers.")
        parser.add_argument("--batch-size", type=int, default=PROBE_BATCH_SIZE, help="Servers per batch.")
        parser.add_argument("--concurrency", type=int, default=PROBE_CONCURRENCY, help="Probes in flight.")

    def handle(self, *args: Any, **options: Any) -> None:
        limit = options["limit"]
        if limit is not None and limit < 0:
            limit = 0
        # `limit or count` would treat 0 as "no limit", so spell the default out.
        target = min(limit if limit is not None else probeable_server_count(), probeable_server_count())
        if target == 0:
            self.stdout.write("no probeable servers: crawl the registry first")
            return

        self.stdout.write(f"probing {target} server(s), {options['concurrency']} at a time")
        probed = 0
        while probed < target:
            batch = probe_stalest_servers(
                batch_size=min(options["batch_size"], target - probed),
                concurrency=options["concurrency"],
            )
            if batch == 0:
                # Every remaining server failed to apply; looping again would not change that.
                break
            probed += batch
            self.stdout.write(f"  {probed}/{target}")

        self.stdout.write(self.style.SUCCESS(f"probed {probed} server(s)"))
