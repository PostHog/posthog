from __future__ import annotations

import asyncio
from typing import Any

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.posthog_ai.eval_harness.scorers.contract import AsyncOnlyScorerMixin, Score, Scorer


class CreatedFlagConfiguration(AsyncOnlyScorerMixin, Scorer):
    def _name(self) -> str:
        return "created_flag_configuration"

    @staticmethod
    def _read_flags(team_id: int, key: str) -> list[dict[str, Any]]:
        return list(FeatureFlag.objects.filter(team_id=team_id, key=key).values("active", "archived", "filters"))

    async def _run_eval_async(
        self, output: dict[str, Any] | None, expected: dict[str, Any] | None = None, **kwargs: Any
    ) -> Score:
        seed = (output or {}).get("seed") or {}
        spec = (expected or {}).get(self._name())
        if not seed.get("team_id") or not spec:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Missing seed or expected configuration"})

        flags = await asyncio.to_thread(self._read_flags, seed["team_id"], spec["key"])
        if len(flags) != 1:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Expected one flag with the requested key"})

        flag = flags[0]
        filters = flag["filters"] or {}
        groups = filters.get("groups") or []
        variants = (filters.get("multivariate") or {}).get("variants") or []
        checks = {
            "active": flag["active"] and not flag["archived"],
            "boolean": not variants,
            "person_targeting": filters.get("aggregation_group_type_index") is None,
            "no_extra_audience": not filters.get("super_groups") and len(groups) == 1,
        }
        if len(groups) == 1:
            group = groups[0]
            properties = group.get("properties") or []
            checks["rollout"] = group.get("rollout_percentage") == spec["rollout_percentage"]
            checks["audience"] = False
            if len(properties) == 1:
                property_filter = properties[0]
                value = property_filter.get("value")
                values = value if isinstance(value, list) else [value]
                checks["audience"] = values == spec["property"]["value"] and all(
                    property_filter.get(key) == spec["property"][key] for key in ("key", "type", "operator")
                )

        failed = [name for name, passed in checks.items() if not passed]
        return Score(name=self._name(), score=float(not failed), metadata={"failed_checks": failed})
