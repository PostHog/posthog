from types import SimpleNamespace
from typing import Any

from unittest.mock import patch

from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase

from parameterized import parameterized

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import WAIT_TIMEOUT_ERROR
from products.engineering_analytics.backend.logic import ci_precompute

_MODULE = "products.engineering_analytics.backend.logic.ci_precompute"


class TestRefreshAfterLoad(SimpleTestCase):
    @parameterized.expand(
        [
            ("stored", SimpleNamespace(ready=True, errors=[]), True),
            ("out_of_budget", SimpleNamespace(ready=False, errors=[WAIT_TIMEOUT_ERROR]), True),
            ("insert_failed", SimpleNamespace(ready=False, errors=["Code: 241. Memory limit exceeded"]), False),
            ("refresh_raised", RuntimeError("connection lost"), False),
        ]
    )
    def test_next_load_refreshes_unless_an_insert_failed(
        self, _name: str, outcome: Any, next_load_refreshes: bool
    ) -> None:
        team = SimpleNamespace(pk=1)
        source = SimpleNamespace(source_id="source", repository="posthog/posthog")
        lookup = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}

        with (
            patch(f"{_MODULE}.cache", LocMemCache(self.id(), {})),
            patch(f"{_MODULE}.team_flag", return_value=True),
            patch(f"{_MODULE}.resolve_precompute_sources", return_value=[source]),
            patch(f"{_MODULE}.Database.create_for"),
            patch(f"{_MODULE}.create_default_modifiers_for_team"),
            patch(f"{_MODULE}.ensure_stored", **lookup) as mock_ensure,
        ):
            try:
                ci_precompute.refresh_after_load(team)  # type: ignore[arg-type]
            except RuntimeError:
                pass
            first_load_calls = mock_ensure.call_count
            mock_ensure.side_effect = None
            mock_ensure.return_value = SimpleNamespace(ready=True, errors=[])
            ci_precompute.refresh_after_load(team)  # type: ignore[arg-type]

        assert (mock_ensure.call_count > first_load_calls) is next_load_refreshes
