"""Composing the serving manifest from the day's models.

The training dag is the only place that knows every family's candidate and champion at once, so it
picks the set the scoring sweep runs. This module is that choice as pure functions over the
`metadata.json` records; `training/dag.py` owns the S3 reads, the publishing and the telemetry.

The served entry is the model the `served.json` pointer names, so the served model changes only
when a person runs `inbox_ranking_promote_job`. The other entries are there so one pass produces several scores: an online paired read
and a later interleaving then need no rescoring of the same reports. A pinned entry is there so an
owner's `served` override can name it.
"""

import datetime
from collections.abc import Mapping, Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.signals.backend.artefact_schemas import MAX_RANKING_MODEL_RESULTS
from products.signals.backend.ranking.model_contract import readable_head_names, trained_head_files
from products.signals.backend.ranking.model_store import ONNX_PROJECT_VECTOR_KINDS_KEY
from products.signals.backend.ranking.serving_manifest import (
    CROSS_FAMILY_ROLE,
    DAILY_CANDIDATE_ROLE,
    DEFAULT_MODEL_KIND,
    ONNX_MODEL_FILE,
    ONNX_MODEL_KIND,
    PINNED_ROLE,
    SERVED_ROLE,
    ServingManifest,
    ServingManifestEntry,
    model_key,
    serving_model_prefix,
)
from products.signals.dags.inbox_ranking.training.heads import HEADS_BY_NAME


@frozen
class FamilyModels:
    """One family's two records for the partition: the candidate fit that day, and the family's
    `champion.json`. Either can be absent. Nothing writes `champion.json` anymore, so a champion is
    the last version the retired automatic promotion chose, and it serves only as a cross-family
    read."""

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
    models are named: the holdout fits grade a promotion and never serve."""
    heads = sorted(trained_head_files(metadata, HEADS_BY_NAME))
    if not heads:
        return None
    key = model_key(metadata["model_name"], metadata["model_version"])
    # A model published before the field existed is per-head XGBoost, so the old default reads
    # as what it is rather than as missing.
    model_kind = metadata.get("model_kind") or DEFAULT_MODEL_KIND
    return ServingManifestEntry(
        key=key,
        model_name=metadata["model_name"],
        model_version=metadata["model_version"],
        model_kind=model_kind,
        roles=list(roles),
        labels=dict(labels),
        prefix=serving_model_prefix(prefix, key),
        heads=heads,
        model_file=ONNX_MODEL_FILE if model_kind == ONNX_MODEL_KIND else None,
        reads_project_vectors=bool(metadata.get(ONNX_PROJECT_VECTOR_KINDS_KEY)),
    )


def compose_manifest(
    families: Sequence[FamilyModels],
    *,
    served: Mapping[str, Any] | None,
    prefix: str,
    now: datetime.datetime,
    pinned: Sequence[Mapping[str, Any]] = (),
) -> ManifestDecision:
    """`served` holds the metadata of the model the `served.json` pointer names, and `pinned` the
    metadata of the models the `pin` override keeps. The caller checks that their files exist,
    because a manifest that names a missing file is never published."""
    if served is None:
        return ManifestDecision(manifest=None, reason="no served pointer")
    served_family = served["model_name"]
    served_entry = _entry(
        served,
        roles=[SERVED_ROLE],
        labels={"reason": "named by the served pointer"},
        prefix=prefix,
    )
    if served_entry is None:
        return ManifestDecision(
            manifest=None, reason=f"served model {served_family}@{served['model_version']} has no head to load"
        )

    entries = [served_entry]
    served_models = next((family for family in families if family.name == served_family), None)
    candidate = served_models.candidate if served_models is not None else None
    # A candidate at the champion's own version is the champion, so scoring it twice would only
    # spend the artefact's result budget on a duplicate.
    if (
        candidate is not None
        and candidate["model_version"] != served_entry.model_version
        and readable_head_names(candidate)
    ):
        daily = _entry(
            candidate,
            roles=[DAILY_CANDIDATE_ROLE],
            labels={"reason": f"today's {served_family} candidate, paired against the served model"},
            prefix=prefix,
        )
        if daily is not None:
            entries.append(daily)

    for metadata in pinned:
        pin = _entry(
            metadata,
            roles=[PINNED_ROLE],
            labels={"reason": "pinned by the inbox-ranking-overrides flag"},
            prefix=prefix,
        )
        if pin is not None and pin.key not in {entry.key for entry in entries}:
            entries.append(pin)

    for family in families:
        if family.name == served_family or family.champion is None or not readable_head_names(family.champion):
            continue
        cross = _entry(
            family.champion,
            roles=[CROSS_FAMILY_ROLE],
            labels={"reason": f"champion of {family.name}"},
            prefix=prefix,
        )
        if cross is not None and cross.key not in {entry.key for entry in entries}:
            entries.append(cross)

    # The served entry and the paired candidate are the reads the sweep exists for, so the cap
    # falls on the pinned and cross-family entries, cross-family first. They are last in
    # `entries`, the cross-family ones in family registration order.
    return ManifestDecision(
        manifest=ServingManifest(manifest_version=now.isoformat(), models=entries[:MAX_RANKING_MODEL_RESULTS]),
        reason="composed",
    )
