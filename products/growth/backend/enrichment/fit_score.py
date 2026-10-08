import json
import hashlib
from copy import deepcopy
from dataclasses import field
from datetime import timedelta
from typing import Annotated, Any, Literal, Optional, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from posthog.dataclasses import frozen

from products.growth.backend.enrichment.icp_lists import CuratedLists
from products.growth.backend.enrichment.scoring_rules import DISALLOWED_FUNCTIONS, compile_scoring_formula

from common.hogvm.python.execute import execute_bytecode

SCORE_VERSION = "v0.7"

STATUS_SCORED = "scored"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_NOT_FOUND = "not_found"
STATUS_DISQUALIFIED = "disqualified"

SCORING_TIMEOUT = timedelta(milliseconds=100)
FlagValue = bool | int | Annotated[float, Field(allow_inf_nan=False)] | Annotated[str, Field(max_length=1_000)] | None


@frozen
class IcpFitResult:
    status: str
    score: Optional[int] = None
    dq_reason: Optional[str] = None
    components: Optional[dict[str, int]] = None
    flags: dict[str, FlagValue] = field(default_factory=dict)
    version: str = SCORE_VERSION
    lists_version: Optional[str] = None
    input_versions: dict[str, str] = field(default_factory=dict)
    input_hash: str = ""
    input_values: dict[str, Any] = field(default_factory=dict)


class FormulaResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["scored", "insufficient_data", "not_found", "disqualified"]
    score: Annotated[int, Field(ge=0, le=100)] | None = None
    components: Annotated[dict[str, Annotated[int, Field(ge=0, le=100)]], Field(max_length=30)] | None = None
    dq_reason: Annotated[str, Field(max_length=500)] | None = None
    flags: Annotated[dict[Annotated[str, Field(min_length=1, max_length=128)], FlagValue], Field(max_length=32)] = (
        Field(default_factory=dict)
    )

    @model_validator(mode="after")
    def coherent_score(self) -> Self:
        if self.status == STATUS_SCORED:
            if self.score is None or self.components is None or self.score != sum(self.components.values()):
                raise ValueError("A scored result needs components whose points sum to its score")
        elif self.status == STATUS_DISQUALIFIED:
            if self.score != 0 or not self.dq_reason:
                raise ValueError("A disqualified result needs score 0 and a reason")
        elif self.score is not None or self.components is not None:
            raise ValueError("Missing company data must not produce a score or components")
        return self


def build_scoring_inputs(
    payload: Optional[dict[str, Any]],
    *,
    lists: CuratedLists,
    role: Optional[str] = None,
    domain: Optional[str] = None,
    wizard_ai_sdk: bool = False,
    enrichments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "company": payload if isinstance(payload, dict) else None,
        "signup": {"role": role or "", "domain": domain or "", "wizard_ai_sdk": wizard_ai_sdk},
        "enrichments": enrichments if enrichments is not None else {},
        "lists": {
            name: sorted(getattr(lists, name))
            for name in (
                "capital_quality",
                "ai_positive",
                "software_positive",
                "software_negative",
                "dq",
                "quality_investors",
            )
        },
    }


def evaluate_score(source: str, inputs: dict[str, Any]) -> FormulaResult:
    response = execute_bytecode(
        compile_scoring_formula(source),
        globals=inputs,
        timeout=SCORING_TIMEOUT,
        disallowed_functions=DISALLOWED_FUNCTIONS,
    )
    return FormulaResult.model_validate(response.result)


def scoring_input_hash(inputs: dict[str, Any], input_versions: dict[str, str]) -> str:
    encoded = json.dumps(
        {"inputs": inputs, "input_versions": input_versions}, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def score_context(
    inputs: dict[str, Any],
    *,
    source: str,
    lists_version: str,
    input_versions: dict[str, str] | None = None,
) -> IcpFitResult:
    values = deepcopy(inputs)
    versions = dict(input_versions or {})
    input_hash = scoring_input_hash(values, versions)
    result = evaluate_score(source, values)
    return IcpFitResult(
        **result.model_dump(),
        lists_version=lists_version,
        input_versions=versions,
        input_hash=input_hash,
        input_values=values,
    )


def score_company(
    payload: Optional[dict[str, Any]],
    *,
    lists: CuratedLists,
    role: Optional[str] = None,
    domain: Optional[str] = None,
    wizard_ai_sdk: bool = False,
    enrichments: dict[str, Any] | None = None,
    input_versions: dict[str, str] | None = None,
) -> IcpFitResult:
    inputs = build_scoring_inputs(
        payload, lists=lists, role=role, domain=domain, wizard_ai_sdk=wizard_ai_sdk, enrichments=enrichments
    )
    return score_context(inputs, source=lists.rules.source, lists_version=lists.version, input_versions=input_versions)
