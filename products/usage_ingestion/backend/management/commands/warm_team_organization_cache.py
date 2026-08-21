from posthog.caching.usage_ingestion_redis_cache import USAGE_INGESTION_CACHE_ALIAS
from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand

from products.usage_ingestion.backend.team_organization_cache import TEAM_ORGANIZATION_HYPERCACHE_MANAGEMENT_CONFIG


class Command(BaseHyperCacheCommand):
    help = "Warm the usage-ingestion team-to-organization cache"
    dedicated_cache_alias = USAGE_INGESTION_CACHE_ALIAS
    dedicated_cache_setting = "USAGE_INGESTION_REDIS_URL"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_warm_arguments(parser)

    def get_hypercache_config(self):
        return TEAM_ORGANIZATION_HYPERCACHE_MANAGEMENT_CONFIG

    def handle(self, *args, **options):
        if not self.check_dedicated_cache_configured():
            return
        if not self.validate_batch_size(options["batch_size"]):
            return
        if not self.validate_ttl_range(options["min_ttl_days"], options["max_ttl_days"]):
            return
        self.run_warm(
            team_ids=options.get("team_ids"),
            batch_size=options["batch_size"],
            stagger_ttl=not options["no_stagger"],
            min_ttl_days=options["min_ttl_days"],
            max_ttl_days=options["max_ttl_days"],
        )
