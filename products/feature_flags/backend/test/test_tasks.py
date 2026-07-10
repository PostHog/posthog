from posthog.test.base import BaseTest

from products.feature_flags.backend.local_evaluation import flag_definitions_hypercache, update_flag_caches
from products.feature_flags.backend.tasks import clear_team_definitions_cache


class TestClearTeamDefinitionsCache(BaseTest):
    def test_clears_cache_for_existing_team(self):
        update_flag_caches(self.team)
        _, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"

        clear_team_definitions_cache(self.team.id)

        _, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "db"

    def test_missing_team_does_not_raise(self):
        clear_team_definitions_cache(999999999)
