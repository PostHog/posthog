from posthog.caching.usage_ingestion_redis_cache import USAGE_INGESTION_CACHE_ALIAS
from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand

from products.usage_ingestion.backend.team_organization_cache import (
    TEAM_ORGANIZATION_HYPERCACHE_MANAGEMENT_CONFIG,
    verify_team_organization,
)


class Command(BaseHyperCacheCommand):
    help = "Verify the usage-ingestion team-to-organization cache"
    dedicated_cache_alias = USAGE_INGESTION_CACHE_ALIAS
    dedicated_cache_setting = "USAGE_INGESTION_REDIS_URL"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_verify_arguments(parser)

    def get_hypercache_config(self):
        return TEAM_ORGANIZATION_HYPERCACHE_MANAGEMENT_CONFIG

    def verify_team(self, team, verbose: bool, batch_data: dict | None = None) -> dict:
        return verify_team_organization(team, db_batch_data=batch_data, verbose=verbose)

    def handle(self, *args, **options):
        if not self.check_dedicated_cache_configured():
            return

        sample_size = options.get("sample")
        if sample_size is not None and not self.validate_sample_size(sample_size):
            return

        self.run_verification(
            team_ids=options.get("team_ids"),
            sample_size=sample_size,
            verbose=options.get("verbose", False),
            fix=options.get("fix", False),
        )
