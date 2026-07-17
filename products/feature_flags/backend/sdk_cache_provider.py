from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

from django.core.exceptions import ObjectDoesNotExist

import structlog
from posthoganalytics.flag_definition_cache import FlagDefinitionCacheData

if TYPE_CHECKING:
    from posthog.storage.hypercache import HyperCache

logger = structlog.get_logger(__name__)


class HyperCacheFlagProvider:
    """
    Read-only FlagDefinitionCacheProvider that reads flag definitions from the
    existing HyperCache infrastructure instead of polling the API.

    The HyperCache is kept fresh via Django signals (when flags/cohorts change)
    and periodic refresh tasks. This provider eliminates per-process API polling
    by reading directly from the same Redis cache.
    """

    def __init__(self, team_id_resolver: Callable[[], Optional[int]]):
        self._team_id_resolver = team_id_resolver
        self._team_id: Optional[int] = None  # memoized first non-None resolution
        self._hypercache: Optional[HyperCache] = None
        self._logged_resolved_team = False
        self._logged_zero_flags = False

    @classmethod
    def for_static_team(cls, team_id: int) -> HyperCacheFlagProvider:
        """Cloud / E2E / explicit operator override: a fixed, known team id."""
        return cls(team_id_resolver=lambda: team_id)

    @classmethod
    def for_dynamic_resolution(cls, team_id_resolver: Callable[[], Optional[int]]) -> HyperCacheFlagProvider:
        """Local/self-hosted: resolve the team id lazily, retrying while it returns None."""
        return cls(team_id_resolver=team_id_resolver)

    def _resolve_team_id(self) -> Optional[int]:
        # Resolve once and memoize; a None result is NOT cached, so we retry next poll
        # (resolution may run before the first team exists / before migrations).
        if self._team_id is None:
            self._team_id = self._team_id_resolver()
            if self._team_id is not None and not self._logged_resolved_team:
                logger.info("sdk_flag_provider_team_resolved", team_id=self._team_id)
                self._logged_resolved_team = True
        return self._team_id

    def _get_hypercache(self):
        """Lazily resolve the hypercache reference.

        The import is deferred because local_evaluation.py triggers a deep
        import chain (cohort.util → hogql → api → ... → cohort.util) that
        causes a circular ImportError when called during AppConfig.ready().
        By caching the reference after the first successful import, subsequent
        calls skip the import entirely.
        """
        if self._hypercache is None:
            from products.feature_flags.backend.local_evaluation import flag_definitions_hypercache

            self._hypercache = flag_definitions_hypercache
        return self._hypercache

    def get_flag_definitions(self) -> Optional[FlagDefinitionCacheData]:
        team_id = self._resolve_team_id()
        if team_id is None:
            # No self-team resolved (yet) — skip the lookup; the SDK falls back.
            return None
        try:
            data = self._get_hypercache().get_from_cache(team_id)
            if data is not None:
                # Defensive: ensure a valid FlagDefinitionCacheData even if
                # the HyperCache shape drifts in the future.
                result: FlagDefinitionCacheData = {
                    "flags": data.get("flags", []),
                    "group_type_mapping": data.get("group_type_mapping", {}),
                    "cohorts": data.get("cohorts", {}),
                }
                if not result["flags"] and not self._logged_zero_flags:
                    logger.warning(
                        "sdk_flag_provider_zero_flags",
                        team_id=team_id,
                        hint="resolved self-team has no flag definitions; run sync_feature_flags_from_api or set POSTHOG_SELF_TEAM_ID",
                    )
                    self._logged_zero_flags = True
                return result
            return None
        except ImportError:
            # Expected during Django startup — local_evaluation.py has a
            # circular import chain through cohort.util that resolves once
            # all modules finish loading. The SDK's next poll cycle will retry.
            logger.debug("hypercache_flag_provider_import_pending", team_id=team_id)
            return None
        except ObjectDoesNotExist:
            # Self-hosted/local instances often lack the configured self team
            # (POSTHOG_SELF_TEAM_ID, default 2). Returning None lets the SDK fall back to its API fetch.
            logger.debug("hypercache_flag_provider_team_missing", team_id=self._team_id)
            return None
        except Exception:
            logger.exception("hypercache_flag_provider_read_error", team_id=team_id)
            return None

    def should_fetch_flag_definitions(self) -> bool:
        # Never poll the API — HyperCache handles all writes via Django signals
        # and periodic refresh tasks
        return False

    def on_flag_definitions_received(self, data: FlagDefinitionCacheData) -> None:
        pass  # No-op — should_fetch always returns False, so this is never called

    def shutdown(self) -> None:
        pass  # No-op — no locks or resources to release
