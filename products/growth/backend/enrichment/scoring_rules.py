from typing import Annotated, Any, Literal, Self

from django.core.exceptions import ValidationError as DjangoValidationError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Points = Annotated[int, Field(strict=True, ge=0, le=100)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Horizon = Literal["30d_ago", "90d_ago", "180d_ago", "365d_ago"]
AiSource = Literal["harmonic", "wizard", "llm"]
LabelName = Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9_]{0,127}$")]


class RuleModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


class PointThreshold(RuleModel):
    minimum: NonnegativeInt
    points: Points


def _validate_levels(levels: tuple[PointThreshold, ...]) -> tuple[PointThreshold, ...]:
    if any(left.minimum >= right.minimum or left.points > right.points for left, right in zip(levels, levels[1:])):
        raise ValueError("Thresholds must increase strictly and points must not decrease")
    return levels


def points_for(value: int | float, levels: tuple[PointThreshold, ...], fallback: int = 0) -> int:
    return next((level.points for level in reversed(levels) if value >= level.minimum), fallback)


def _maximum_points(levels: tuple[PointThreshold, ...], fallback: int = 0) -> int:
    return max((level.points for level in levels), default=fallback)


class TractionRules(RuleModel):
    traffic_levels: tuple[PointThreshold, ...] = (
        PointThreshold(minimum=1_000, points=5),
        PointThreshold(minimum=10_000, points=10),
        PointThreshold(minimum=100_000, points=15),
    )
    growth_levels: tuple[PointThreshold, ...] = (
        PointThreshold(minimum=15, points=12),
        PointThreshold(minimum=40, points=20),
    )
    growth_horizon: Horizon = "90d_ago"
    minimum_traffic_for_growth: NonnegativeInt = 5_000
    positive_growth_minimum: NonnegativeInt = 0
    positive_growth_points: Points = 5

    _ordered_levels = field_validator("traffic_levels", "growth_levels")(_validate_levels)

    @model_validator(mode="after")
    def coherent_growth(self) -> Self:
        if self.growth_levels and (
            self.growth_levels[0].minimum <= self.positive_growth_minimum
            or self.growth_levels[0].points < self.positive_growth_points
        ):
            raise ValueError("Growth levels must exceed the positive-growth minimum and award at least its points")
        return self


class CapitalRules(RuleModel):
    funding_levels: tuple[PointThreshold, ...] = (
        PointThreshold(minimum=2_000_000, points=14),
        PointThreshold(minimum=10_000_000, points=20),
    )
    funded_minimum: NonnegativeInt = 0
    funded_points: Points = 8
    quality_bonus: Points = 10
    cap: Points = 30
    investor_substring_min_chars: PositiveInt = 8

    _ordered_levels = field_validator("funding_levels")(_validate_levels)

    @model_validator(mode="after")
    def coherent_capital(self) -> Self:
        if self.funding_levels and (
            self.funding_levels[0].minimum <= self.funded_minimum or self.funding_levels[0].points < self.funded_points
        ):
            raise ValueError("Funding levels must exceed the funded minimum and award at least its points")
        if max(self.funded_points, self.quality_bonus, _maximum_points(self.funding_levels)) > self.cap:
            raise ValueError("Capital points and quality bonus must not exceed the capital cap")
        return self


class HeadcountGrowthRules(RuleModel):
    levels: tuple[PointThreshold, ...] = (PointThreshold(minimum=5, points=6), PointThreshold(minimum=15, points=10))
    horizon: Horizon = "180d_ago"
    minimum_hires: PositiveInt = 3
    hires_points: Points = 6
    positive_growth_minimum: NonnegativeInt = 0
    positive_growth_points: Points = 3

    _ordered_levels = field_validator("levels")(_validate_levels)

    @model_validator(mode="after")
    def coherent_growth(self) -> Self:
        if self.levels and (
            self.levels[0].minimum <= self.positive_growth_minimum
            or self.levels[0].points < self.positive_growth_points
        ):
            raise ValueError("Growth levels must exceed the positive-growth minimum and award at least its points")
        return self


class SoftwareRelevanceRules(RuleModel):
    engineering_minimum: NonnegativeInt = 0
    engineering_points: Points = 10
    other_points: Points = 7

    @model_validator(mode="after")
    def coherent_points(self) -> Self:
        if self.engineering_points < self.other_points:
            raise ValueError("Engineering points must be at least other software points")
        return self


class CoverageRules(RuleModel):
    headcount_minimum: PositiveInt = 1
    traffic_minimum: PositiveInt = 100
    funding_minimum: NonnegativeInt = 0
    low_confidence_maximum: Annotated[int, Field(strict=True, ge=0, le=4)] = 1


class ScoringRules(RuleModel):
    schema_version: Literal[1] = 1
    traction: TractionRules = Field(default_factory=TractionRules)
    capital: CapitalRules = Field(default_factory=CapitalRules)
    headcount_growth: HeadcountGrowthRules = Field(default_factory=HeadcountGrowthRules)
    software_relevance: SoftwareRelevanceRules = Field(default_factory=SoftwareRelevanceRules)
    coverage: CoverageRules = Field(default_factory=CoverageRules)
    ai_points: Points = 15
    ai_sources: tuple[AiSource, ...] = ("harmonic", "wizard", "llm")
    ai_labels: Annotated[tuple[LabelName, ...], Field(min_length=1)] = ("ai_pilled",)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_schema_version(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("Schema version must be an integer")
        return value

    @field_validator("ai_sources", "ai_labels")
    @classmethod
    def unique_entries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Entries must be unique")
        return value

    @model_validator(mode="after")
    def bounded_score(self) -> Self:
        maximum = (
            _maximum_points(self.traction.traffic_levels)
            + max(self.traction.positive_growth_points, _maximum_points(self.traction.growth_levels))
            + min(
                self.capital.cap,
                max(self.capital.funded_points, _maximum_points(self.capital.funding_levels))
                + self.capital.quality_bonus,
            )
            + max(
                self.headcount_growth.positive_growth_points,
                self.headcount_growth.hires_points,
                _maximum_points(self.headcount_growth.levels),
            )
            + self.software_relevance.engineering_points
            + (self.ai_points if self.ai_sources else 0)
        )
        if maximum > 100:
            raise ValueError(f"Maximum component points total {maximum}; the ICP score must stay within 0–100")
        return self


def parse_scoring_rules(value: dict[str, Any]) -> ScoringRules:
    return ScoringRules.model_validate(value)


def default_scoring_rules() -> dict[str, Any]:
    return ScoringRules().model_dump(mode="json")


def validate_scoring_rules(value: Any) -> None:
    try:
        parse_scoring_rules(value)
    except ValidationError as error:
        raise DjangoValidationError(
            [
                f"{'.'.join(str(part) for part in item['loc']) or 'scoring_rules'}: {item['msg']}"
                for item in error.errors()
            ]
        ) from error
