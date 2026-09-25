"""Composing the serving manifest from the day's models.

The training dag is the only place that knows every family's candidate and champion at once, so it
picks the set the scoring sweep runs. This module is that choice as pure functions over the
`metadata.json` records; `training/dag.py` owns the S3 reads, the publishing and the telemetry.

The served entry is the champion of one family, so the served model only ever changes through a
promotion. The other entries are there so one pass produces several scores: an online paired read
and a later interleaving then need no rescoring of the same reports.
"""

import datetime
from collections.abc import Mapping, Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import MAX_RANKING_MODEL_RESULTS
from products.signals.backend.ranking.model_contract import readable_head_names, trained_head_files
from products.signals.backend.ranking.serving_manifest import (
    CROSS_FAMILY_ROLE,
    DAILY_CANDIDATE_ROLE,
    DEFAULT_MODEL_KIND,
    SERVED_ROLE,
    ServingManifest,
    ServingManifestEntry,
    model_key,
    serving_model_prefix,
)
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME


@frozen
class FamilyModels:
    """One family's two records for the partition: the candidate fit that day, and the pointer the
    sweep would serve. Either can be absent — a family can be registered before its first candidate,
    and no family has a champion until the first promotion."""

    name: str
    candidate: Mapping[str, Any] | None
    champion: Mapping[str, Any] | None


@frozen
class ManifestDecision:
    """The manifest to publish, or None with the reason nothing is published. A run that writes
    nothing leaves the previous manifest, and the models it names, in place."""

    manifest: ServingManifest | None
    reason: str


def _entry(
    metadata: Mapping[str, Any],
    *,
    roles: Sequence[str],
    labels: Mapping[str, str],
    prefix: str,
) -> ServingManifestEntry | None:
    """One manifest entry, or None when the model has no head a store could load. Only the refit
    boosters are named: the holdout fits grade a promotion and never serve."""
    heads = sorted(trained_head_files(metadata, HEADS_BY_NAME))
    if not heads:
        return None
    key = model_key(metadata["model_name"], metadata["model_version"])
    return ServingManifestEntry(
        key=key,
        model_name=metadata["model_name"],
        model_version=metadata["model_version"],
        # A model published before the field existed is per-head XGBoost, so the old default reads
        # as what it is rather than as missing.
        model_kind=metadata.get("model_kind") or DEFAULT_MODEL_KIND,
        roles=list(roles),
        labels=dict(labels),
        prefix=serving_model_prefix(prefix, key),
        heads=heads,
    )


def compose_manifest(
    families: Sequence[FamilyModels],
    *,
    served_family: str,
    prefix: str,
    now: datetime.datetime,
) -> ManifestDecision:
    by_name = {family.name: family for family in families}
    served_models = by_name.get(served_family)
    if served_models is None:
        return ManifestDecision(manifest=None, reason=f"served family {served_family} is not registered")
    if served_models.champion is None:
        return ManifestDecision(manifest=None, reason=f"served family {served_family} has no champion yet")
    served = _entry(
        served_models.champion,
        roles=[SERVED_ROLE],
        labels={"reason": f"champion of the served family {served_family}"},
        prefix=prefix,
    )
    if served is None:
        return ManifestDecision(
            manifest=None, reason=f"served family {served_family} champion has no head booster to load"
        )

    entries = [served]
    candidate = served_models.candidate
    # A candidate at the champion's own version is the champion, so scoring it twice would only
    # spend the artefact's result budget on a duplicate.
    if candidate is not None and candidate["model_version"] != served.model_version and readable_head_names(candidate):
        daily = _entry(
            candidate,
            roles=[DAILY_CANDIDATE_ROLE],
            labels={"reason": f"today's {served_family} candidate, paired against the served champion"},
            prefix=prefix,
        )
        if daily is not None:
            entries.append(daily)

    for family in families:
        if family.name == served_family or family.champion is None or not readable_head_names(family.champion):
            continue
        cross = _entry(
            family.champion,
            roles=[CROSS_FAMILY_ROLE],
            labels={"reason": f"champion of {family.name}"},
            prefix=prefix,
        )
        if cross is not None:
            entries.append(cross)

    # The served entry and the paired candidate are the reads the sweep exists for, so the cap
    # falls on the cross-family entries. They are last in `entries`, in family registration order.
    return ManifestDecision(
        manifest=ServingManifest(manifest_version=now.isoformat(), models=entries[:MAX_RANKING_MODEL_RESULTS]),
        reason="composed",
    )
