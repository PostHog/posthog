"""The serving manifest: which ranking models the scoring sweep runs, and which one is served.

The training dag decides the set. It knows every candidate's version, the heads each candidate
could fit, and each family's champion, so the choice belongs there rather than in the sweep. The
dag writes the decision as one small JSON object in the deployment's own object store, next to the
model files it also publishes, and the sweep reads both from there. The dataset bucket the training
dag writes its history to stays out of the serving path.

This module is the contract between the two. The schema, the role vocabulary and the object keys
live here, in the backend package that already holds the feature contract, so the writer and the
reader cannot disagree about them. The validators run at write time, so a manifest the sweep could
not act on is refused by the dag that composed it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from products.signals.backend.artefact_schemas import MAX_RANKING_MODEL_RESULTS, RANKING_SERVED_ROLE

# The one role a reader acts on, taken from the artefact schema so the manifest and the
# `ranking_score` rows it produces name the served model the same way.
SERVED_ROLE = RANKING_SERVED_ROLE
# The served family's model for the partition being trained, carried so a paired read compares the
# champion against the day's fit without a second scoring pass.
DAILY_CANDIDATE_ROLE = "daily_candidate"
# Another family's champion, scored alongside so a later interleaving needs no rescoring.
CROSS_FAMILY_ROLE = "cross_family"

# The learner a model store loads the booster with. Every family is per-head XGBoost today, and a
# model published before the field existed is one of those, so this is also the read fallback.
DEFAULT_MODEL_KIND = "xgboost"

MANIFEST_FILE = "manifest.json"
METADATA_FILE = "metadata.json"

_SERVING_SEGMENT = "serving"


def serving_manifest_key(prefix: str) -> str:
    return f"{prefix}/{_SERVING_SEGMENT}/{MANIFEST_FILE}"


def serving_model_prefix(prefix: str, key: str) -> str:
    """Where one model's `metadata.json` and head boosters sit. Keyed by `<name>@<version>`, so a
    version is published once however many manifests name it."""
    return f"{prefix}/{_SERVING_SEGMENT}/models/{key}"


def model_key(model_name: str, model_version: str) -> str:
    return f"{model_name}@{model_version}"


class ServingManifestEntry(BaseModel):
    """One model the sweep runs, and where to load it from."""

    # Pydantic reserves the `model_` prefix for its own API. The fields mirror the training dag's
    # own columns and `RankingModelResult`, which is the reason they carry these names.
    model_config = ConfigDict(protected_namespaces=())

    key: str = Field(description="`<model_name>@<model_version>`, the identity every consumer uses.")
    model_name: str = Field(description="Feature family the model belongs to, e.g. `report_embeddings`.")
    model_version: str = Field(description="Training partition the model was fit on, as `YYYY-MM-DD`.")
    model_kind: str = Field(description="Learner the model store loads the booster with, e.g. `xgboost`.")
    roles: list[str] = Field(
        min_length=1,
        description=f"Why this model is in the manifest. Exactly one entry carries `{SERVED_ROLE}`.",
    )
    labels: dict[str, str] = Field(default_factory=dict, description="Free text about the entry, for a reader.")
    prefix: str = Field(description="Object-store prefix holding this model's `metadata.json` and head boosters.")
    heads: list[str] = Field(min_length=1, description="Outcome heads with a booster under `prefix`.")

    @field_validator("key", "model_name", "model_version", "model_kind", "prefix")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v

    @model_validator(mode="after")
    def key_matches_the_identity(self) -> ServingManifestEntry:
        expected = model_key(self.model_name, self.model_version)
        if self.key != expected:
            raise ValueError(f"key {self.key!r} does not match its model {expected!r}")
        return self


class ServingManifest(BaseModel):
    """The models one scoring pass runs. A pass writes one `ranking_score` row naming all of them."""

    manifest_version: str = Field(description="ISO timestamp of the write, stamped onto every score it produces.")
    models: list[ServingManifestEntry] = Field(
        min_length=1,
        # The cap is the artefact's, so a manifest can never produce a row `RankingScore` refuses.
        max_length=MAX_RANKING_MODEL_RESULTS,
        description="Every model the pass runs, served first.",
    )

    @field_validator("manifest_version")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty or whitespace-only")
        return v

    @model_validator(mode="after")
    def one_served_model_under_unique_keys(self) -> ServingManifest:
        keys = [entry.key for entry in self.models]
        if len(set(keys)) != len(keys):
            raise ValueError(f"model keys must be unique, got {keys}")
        served = [entry.key for entry in self.models if SERVED_ROLE in entry.roles]
        if len(served) != 1:
            raise ValueError(f"exactly one model must carry the {SERVED_ROLE!r} role, got {served}")
        return self

    @property
    def served(self) -> ServingManifestEntry:
        return next(entry for entry in self.models if SERVED_ROLE in entry.roles)
