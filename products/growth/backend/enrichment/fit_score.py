import dataclasses
from datetime import timedelta
from typing import Annotated, Any, Literal, Optional, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from posthog.dataclasses import frozen

from products.growth.backend.enrichment.icp_lists import CuratedLists, norm
from products.growth.backend.enrichment.scoring_rules import DISALLOWED_FUNCTIONS, compile_scoring_formula

from common.hogvm.python.execute import execute_bytecode

SCORE_VERSION = "v0.7"

STATUS_SCORED = "scored"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_NOT_FOUND = "not_found"
STATUS_DISQUALIFIED = "disqualified"

SCORING_TIMEOUT = timedelta(milliseconds=100)


@frozen
class AiPilledLabel:
    result_id: str
    fetch_id: str
    prompt_version: str
    prompt_hash: str


@dataclasses.dataclass(frozen=True)
class IcpFitResult:
    """One org's fit evaluation. score is None unless status is scored/disqualified."""

    status: str
    score: Optional[int] = None
    dq_reason: Optional[str] = None
    components: Optional[dict[str, int]] = None
    quality_investor: Optional[bool] = None
    data_coverage: Optional[int] = None
    low_confidence: Optional[bool] = None
    agency_flag: Optional[bool] = None
    nonprofit_flag: Optional[bool] = None
    wizard_ai_sdk: Optional[bool] = None
    ai_pilled_source: Optional[str] = None
    ai_pilled_label: AiPilledLabel | None = None
    ai_pilled_label_result_id: str | None = None
    version: str = SCORE_VERSION
    lists_version: Optional[str] = None


class FormulaResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["scored", "insufficient_data", "not_found", "disqualified"]
    score: Annotated[int, Field(ge=0, le=100)] | None = None
    components: Annotated[dict[str, Annotated[int, Field(ge=0, le=100)]], Field(max_length=30)] | None = None
    dq_reason: Annotated[str, Field(max_length=500)] | None = None
    quality_investor: bool | None = None
    data_coverage: Annotated[int, Field(ge=0)] | None = None
    low_confidence: bool | None = None
    agency_flag: bool | None = None
    nonprofit_flag: bool | None = None
    wizard_ai_sdk: bool | None = None
    ai_pilled_source: (
        Literal["harmonic", "wizard", "llm", "both", "harmonic+llm", "wizard+llm", "harmonic+wizard+llm"] | None
    ) = None

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
    ai_pilled_label: AiPilledLabel | None = None,
) -> dict[str, Any]:
    company = payload if isinstance(payload, dict) else None
    tags = (company or {}).get("tags_v2") or []
    funding = (company or {}).get("funding") or {}
    return {
        "company": company,
        "tags": [norm(tag.get("display_value")) for tag in tags if isinstance(tag, dict)],
        "tag_types": [tag.get("type") for tag in tags if isinstance(tag, dict)],
        "investors": [
            norm(investor.get("name")) for investor in funding.get("investors") or [] if isinstance(investor, dict)
        ],
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
        "role": role or "",
        "domain": domain or "",
        "wizard_ai_sdk": wizard_ai_sdk,
        "ai_pilled": ai_pilled_label is not None,
    }


def score_company(
    payload: Optional[dict[str, Any]],
    *,
    lists: CuratedLists,
    role: Optional[str] = None,
    domain: Optional[str] = None,
    wizard_ai_sdk: bool = False,
    ai_pilled_label: AiPilledLabel | None = None,
) -> IcpFitResult:
    inputs = build_scoring_inputs(
        payload, lists=lists, role=role, domain=domain, wizard_ai_sdk=wizard_ai_sdk, ai_pilled_label=ai_pilled_label
    )
    response = execute_bytecode(
        compile_scoring_formula(lists.rules.source),
        globals=inputs,
        timeout=SCORING_TIMEOUT,
        disallowed_functions=DISALLOWED_FUNCTIONS,
    )
    result = FormulaResult.model_validate(response.result)
    uses_label = result.status == STATUS_SCORED and "llm" in (result.ai_pilled_source or "").split("+")
    return IcpFitResult(
        **result.model_dump(exclude={"wizard_ai_sdk"}),
        wizard_ai_sdk=wizard_ai_sdk if result.status == STATUS_SCORED else None,
        ai_pilled_label=ai_pilled_label if uses_label else None,
        lists_version=lists.version,
    )
