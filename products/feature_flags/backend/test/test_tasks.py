import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.storage import object_storage
from posthog.storage.team_metadata_cache import team_metadata_hypercache, update_team_metadata_cache

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

    def test_clears_team_metadata_even_when_definitions_delete_fails(self):
        update_team_metadata_cache(self.team)
        cache_key = team_metadata_hypercache.get_cache_key(self.team)

        with (
            patch.object(flag_definitions_hypercache, "delete_cache_entry", side_effect=RuntimeError("redis down")),
            pytest.raises(RuntimeError),
        ):
            clear_team_definitions_cache(self.team.id, api_token=self.team.api_token)

        assert team_metadata_hypercache.cache_client.get(cache_key) is None
        assert object_storage.read(cache_key, missing_ok=True) is None
