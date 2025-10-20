# mypy: disable-error-code="assignment"

from __future__ import annotations

from datetime import datetime
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, RootModel


class ToolInputs(RootModel[Any]):
    root: Any


class Data(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    insightId: str
    dashboardId: Annotated[int, Field(gt=0)]


class DashboardAddInsightSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: Data


class Data1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[str, Field(min_length=1)]
    description: str | None = None
    pinned: bool | None = None
    tags: list[str] | None = None


class DashboardCreateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: Data1


class DashboardDeleteSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dashboardId: float


class Data2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    limit: Annotated[int | None, Field(gt=0)] = None
    offset: Annotated[int | None, Field(ge=0)] = None
    search: str | None = None
    pinned: bool | None = None


class DashboardGetAllSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: Data2 | None = None


class DashboardGetSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dashboardId: float


class Data3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    description: str | None = None
    pinned: bool | None = None
    tags: list[str] | None = None


class DashboardUpdateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dashboardId: float
    data: Data3


class DocumentationSearchSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    query: str


class ErrorTrackingDetailsSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    issueId: UUID
    dateFrom: datetime | None = None
    dateTo: datetime | None = None


class OrderBy(StrEnum):
    OCCURRENCES = "occurrences"
    FIRST_SEEN = "first_seen"
    LAST_SEEN = "last_seen"
    USERS = "users"
    SESSIONS = "sessions"


class OrderDirection(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


class Status(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    ALL = "all"
    SUPPRESSED = "suppressed"


class ErrorTrackingListSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    orderBy: OrderBy | None = None
    dateFrom: datetime | None = None
    dateTo: datetime | None = None
    orderDirection: OrderDirection | None = None
    filterTestAccounts: bool | None = None
    status: Status | None = None


class Type(StrEnum):
    """
    Experiment type: 'product' for backend/API changes, 'web' for frontend UI changes
    """

    PRODUCT = "product"
    WEB = "web"


class MetricType(StrEnum):
    """
    Metric type: 'mean' for average values (revenue, time spent), 'funnel' for conversion flows, 'ratio' for comparing two metrics
    """

    MEAN = "mean"
    FUNNEL = "funnel"
    RATIO = "ratio"


class PrimaryMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    """
    Human-readable metric name
    """
    metric_type: MetricType
    """
    Metric type: 'mean' for average values (revenue, time spent), 'funnel' for conversion flows, 'ratio' for comparing two metrics
    """
    event_name: str
    """
    REQUIRED for metrics to work: PostHog event name (e.g., '$pageview', 'add_to_cart', 'purchase'). For funnels, this is the first step. Use '$pageview' if unsure. Search project-property-definitions tool for available events.
    """
    funnel_steps: list[str] | None = None
    """
    For funnel metrics only: Array of event names for each funnel step (e.g., ['product_view', 'add_to_cart', 'checkout', 'purchase'])
    """
    properties: dict[str, Any] | None = None
    """
    Event properties to filter on
    """
    description: str | None = None
    """
    What this metric measures and why it's important for the experiment
    """


class MetricType1(StrEnum):
    """
    Metric type: 'mean' for average values, 'funnel' for conversion flows, 'ratio' for comparing two metrics
    """

    MEAN = "mean"
    FUNNEL = "funnel"
    RATIO = "ratio"


class SecondaryMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    """
    Human-readable metric name
    """
    metric_type: MetricType1
    """
    Metric type: 'mean' for average values, 'funnel' for conversion flows, 'ratio' for comparing two metrics
    """
    event_name: str
    """
    REQUIRED: PostHog event name. Use '$pageview' if unsure.
    """
    funnel_steps: list[str] | None = None
    """
    For funnel metrics only: Array of event names for each funnel step
    """
    properties: dict[str, Any] | None = None
    """
    Event properties to filter on
    """
    description: str | None = None
    """
    What this secondary metric measures
    """


class Variant(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    """
    Variant key (e.g., 'control', 'variant_a', 'new_design')
    """
    name: str | None = None
    """
    Human-readable variant name
    """
    rollout_percentage: Annotated[float, Field(ge=0.0, le=100.0)]
    """
    Percentage of users to show this variant
    """


class ExperimentCreateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[str, Field(min_length=1)]
    """
    Experiment name - should clearly describe what is being tested
    """
    description: str | None = None
    """
    Detailed description of the experiment hypothesis, what changes are being tested, and expected outcomes
    """
    feature_flag_key: str
    """
    Feature flag key (letters, numbers, hyphens, underscores only). IMPORTANT: First search for existing feature flags that might be suitable using the feature-flags-get-all tool, then suggest reusing existing ones or creating a new key based on the experiment name
    """
    type: Type | None = Type.PRODUCT
    """
    Experiment type: 'product' for backend/API changes, 'web' for frontend UI changes
    """
    primary_metrics: list[PrimaryMetric] | None = None
    """
    Primary metrics to measure experiment success. IMPORTANT: Each metric needs event_name to track data. For funnels, provide funnel_steps array with event names for each step. Ask user what events they track, or use project-property-definitions to find available events.
    """
    secondary_metrics: list[SecondaryMetric] | None = None
    """
    Secondary metrics to monitor for potential side effects or additional insights. Each metric needs event_name.
    """
    variants: list[Variant] | None = None
    """
    Experiment variants. If not specified, defaults to 50/50 control/test split. Ask user how many variants they need and what each tests
    """
    minimum_detectable_effect: float | None = 30
    """
    Minimum detectable effect in percentage. Lower values require more users but detect smaller changes. Suggest 20-30% for most experiments
    """
    filter_test_accounts: bool | None = True
    """
    Whether to filter out internal test accounts
    """
    target_properties: dict[str, Any] | None = None
    """
    Properties to target specific user segments (e.g., country, subscription type)
    """
    draft: bool | None = True
    """
    Create as draft (true) or launch immediately (false). Recommend draft for review first
    """
    holdout_id: float | None = None
    """
    Holdout group ID if this experiment should exclude users from other experiments
    """


class ExperimentDeleteSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experimentId: float
    """
    The ID of the experiment to delete
    """


class ExperimentGetAllSchema(BaseModel):
    pass
    model_config = ConfigDict(
        extra="forbid",
    )


class ExperimentGetSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experimentId: float
    """
    The ID of the experiment to retrieve
    """


class ExperimentResultsGetSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experimentId: float
    """
    The ID of the experiment to get comprehensive results for
    """
    refresh: bool
    """
    Force refresh of results instead of using cached values
    """


class PrimaryMetric1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    """
    Human-readable metric name
    """
    metric_type: MetricType1
    """
    Metric type: 'mean' for average values, 'funnel' for conversion flows, 'ratio' for comparing two metrics
    """
    event_name: str
    """
    PostHog event name (e.g., '$pageview', 'add_to_cart', 'purchase')
    """
    funnel_steps: list[str] | None = None
    """
    For funnel metrics only: Array of event names for each funnel step
    """
    properties: dict[str, Any] | None = None
    """
    Event properties to filter on
    """
    description: str | None = None
    """
    What this metric measures
    """


class MetricType3(StrEnum):
    """
    Metric type
    """

    MEAN = "mean"
    FUNNEL = "funnel"
    RATIO = "ratio"


class SecondaryMetric1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    """
    Human-readable metric name
    """
    metric_type: MetricType3
    """
    Metric type
    """
    event_name: str
    """
    PostHog event name
    """
    funnel_steps: list[str] | None = None
    """
    For funnel metrics only: Array of event names
    """
    properties: dict[str, Any] | None = None
    """
    Event properties to filter on
    """
    description: str | None = None
    """
    What this metric measures
    """


class Conclude(StrEnum):
    """
    Conclude experiment with result
    """

    WON = "won"
    LOST = "lost"
    INCONCLUSIVE = "inconclusive"
    STOPPED_EARLY = "stopped_early"
    INVALID = "invalid"


class ExperimentUpdateInputSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    """
    Update experiment name
    """
    description: str | None = None
    """
    Update experiment description
    """
    primary_metrics: list[PrimaryMetric1] | None = None
    """
    Update primary metrics
    """
    secondary_metrics: list[SecondaryMetric1] | None = None
    """
    Update secondary metrics
    """
    minimum_detectable_effect: float | None = None
    """
    Update minimum detectable effect in percentage
    """
    launch: bool | None = None
    """
    Launch experiment (set start_date) or keep as draft
    """
    conclude: Conclude | None = None
    """
    Conclude experiment with result
    """
    conclusion_comment: str | None = None
    """
    Comment about experiment conclusion
    """
    restart: bool | None = None
    """
    Restart concluded experiment (clears end_date and conclusion)
    """
    archive: bool | None = None
    """
    Archive or unarchive experiment
    """


class MetricType4(StrEnum):
    """
    Metric type: 'mean' for average values, 'funnel' for conversion flows, 'ratio' for comparing two metrics
    """

    MEAN = "mean"
    FUNNEL = "funnel"
    RATIO = "ratio"


class PrimaryMetric2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    """
    Human-readable metric name
    """
    metric_type: MetricType4
    """
    Metric type: 'mean' for average values, 'funnel' for conversion flows, 'ratio' for comparing two metrics
    """
    event_name: str
    """
    PostHog event name (e.g., '$pageview', 'add_to_cart', 'purchase')
    """
    funnel_steps: list[str] | None = None
    """
    For funnel metrics only: Array of event names for each funnel step
    """
    properties: dict[str, Any] | None = None
    """
    Event properties to filter on
    """
    description: str | None = None
    """
    What this metric measures
    """


class MetricType5(StrEnum):
    """
    Metric type
    """

    MEAN = "mean"
    FUNNEL = "funnel"
    RATIO = "ratio"


class SecondaryMetric2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    """
    Human-readable metric name
    """
    metric_type: MetricType5
    """
    Metric type
    """
    event_name: str
    """
    PostHog event name
    """
    funnel_steps: list[str] | None = None
    """
    For funnel metrics only: Array of event names
    """
    properties: dict[str, Any] | None = None
    """
    Event properties to filter on
    """
    description: str | None = None
    """
    What this metric measures
    """


class Data4(BaseModel):
    """
    The experiment data to update using user-friendly format
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    """
    Update experiment name
    """
    description: str | None = None
    """
    Update experiment description
    """
    primary_metrics: list[PrimaryMetric2] | None = None
    """
    Update primary metrics
    """
    secondary_metrics: list[SecondaryMetric2] | None = None
    """
    Update secondary metrics
    """
    minimum_detectable_effect: float | None = None
    """
    Update minimum detectable effect in percentage
    """
    launch: bool | None = None
    """
    Launch experiment (set start_date) or keep as draft
    """
    conclude: Conclude | None = None
    """
    Conclude experiment with result
    """
    conclusion_comment: str | None = None
    """
    Comment about experiment conclusion
    """
    restart: bool | None = None
    """
    Restart concluded experiment (clears end_date and conclusion)
    """
    archive: bool | None = None
    """
    Archive or unarchive experiment
    """


class ExperimentUpdateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experimentId: float
    """
    The ID of the experiment to update
    """
    data: Data4
    """
    The experiment data to update using user-friendly format
    """


class Operator(StrEnum):
    EXACT = "exact"
    IS_NOT = "is_not"
    IS_SET = "is_set"
    IS_NOT_SET = "is_not_set"
    ICONTAINS = "icontains"
    NOT_ICONTAINS = "not_icontains"
    REGEX = "regex"
    NOT_REGEX = "not_regex"
    IS_CLEANED_PATH_EXACT = "is_cleaned_path_exact"
    exact_1 = "exact"
    is_not_1 = "is_not"
    is_set_1 = "is_set"
    is_not_set_1 = "is_not_set"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    MIN = "min"
    MAX = "max"
    exact_2 = "exact"
    is_not_2 = "is_not"
    is_set_2 = "is_set"
    is_not_set_2 = "is_not_set"
    IN_ = "in"
    NOT_IN = "not_in"


class Property(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    value: str | float | bool | list[str] | list[float]
    operator: Operator | None = None


class Group(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    properties: list[Property]
    rollout_percentage: float


class Filters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    groups: list[Group]


class FeatureFlagCreateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str
    key: str
    description: str
    filters: Filters
    active: bool
    tags: list[str] | None = None


class FeatureFlagDeleteSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    flagKey: str


class FeatureFlagGetAllSchema(BaseModel):
    pass
    model_config = ConfigDict(
        extra="forbid",
    )


class FeatureFlagGetDefinitionSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    flagId: Annotated[int | None, Field(gt=0)] = None
    flagKey: str | None = None


class Property1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    value: str | float | bool | list[str] | list[float]
    operator: Operator | None = None


class Group1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    properties: list[Property1]
    rollout_percentage: float


class Filters1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    groups: list[Group1]


class Data5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    description: str | None = None
    filters: Filters1 | None = None
    active: bool | None = None
    tags: list[str] | None = None


class FeatureFlagUpdateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    flagKey: str
    data: Data5


class Kind(StrEnum):
    INSIGHT_VIZ_NODE = "InsightVizNode"
    DATA_VISUALIZATION_NODE = "DataVisualizationNode"


class Query(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Kind
    source: Any | None = None
    """
    For new insights, use the query from your successful query-run tool call. For updates, the existing query can optionally be reused.
    """


class Data6(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str
    query: Query
    description: str | None = None
    favorited: bool
    tags: list[str] | None = None


class InsightCreateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: Data6


class InsightDeleteSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    insightId: str


class InsightGenerateHogQLFromQuestionSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: Annotated[str, Field(max_length=1000)]
    """
    Your natural language query describing the SQL insight (max 1000 characters).
    """


class Data7(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    limit: float | None = None
    offset: float | None = None
    favorited: bool | None = None
    search: str | None = None


class InsightGetAllSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: Data7 | None = None


class InsightGetSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    insightId: str


class InsightQueryInputSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    insightId: str


class Query1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Kind
    source: Any | None = None
    """
    For new insights, use the query from your successful query-run tool call. For updates, the existing query can optionally be reused
    """


class Data8(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str | None = None
    description: str | None = None
    filters: dict[str, Any] | None = None
    query: Query1
    favorited: bool | None = None
    dashboard: float | None = None
    tags: list[str] | None = None


class InsightUpdateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    insightId: str
    data: Data8


class LLMAnalyticsGetCostsSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    projectId: Annotated[int, Field(gt=0)]
    days: float | None = None


class OrganizationGetAllSchema(BaseModel):
    pass
    model_config = ConfigDict(
        extra="forbid",
    )


class OrganizationGetDetailsSchema(BaseModel):
    pass
    model_config = ConfigDict(
        extra="forbid",
    )


class OrganizationSetActiveSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    orgId: UUID


class ProjectEventDefinitionsSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    q: str | None = None
    """
    Search query to filter event names. Only use if there are lots of events.
    """


class ProjectGetAllSchema(BaseModel):
    pass
    model_config = ConfigDict(
        extra="forbid",
    )


class Type1(StrEnum):
    """
    Type of properties to get
    """

    EVENT = "event"
    PERSON = "person"


class ProjectPropertyDefinitionsInputSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Type1
    """
    Type of properties to get
    """
    eventName: str | None = None
    """
    Event name to filter properties by, required for event type
    """
    includePredefinedProperties: bool | None = None
    """
    Whether to include predefined properties
    """


class ProjectSetActiveSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    projectId: Annotated[int, Field(gt=0)]


class DateRange(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: str | None = None
    date_to: str | None = None
    explicitDate: bool | None = None


class Properties(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    value: str | float | list[str] | list[float] | None = None
    operator: str | None = None
    type: str | None = None


class Type2(StrEnum):
    AND_ = "AND"
    OR_ = "OR"


class Value(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    value: str | float | list[str] | list[float] | None = None
    operator: str | None = None
    type: str | None = None


class Properties1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Type2
    values: list[Value]


class Properties2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Type2
    values: list[Value]


class Interval(StrEnum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class Math(StrEnum):
    TOTAL = "total"
    DAU = "dau"
    WEEKLY_ACTIVE = "weekly_active"
    MONTHLY_ACTIVE = "monthly_active"
    UNIQUE_SESSION = "unique_session"
    FIRST_TIME_FOR_USER = "first_time_for_user"
    FIRST_MATCHING_EVENT_FOR_USER = "first_matching_event_for_user"
    AVG = "avg"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"
    P75 = "p75"
    P90 = "p90"
    P95 = "p95"
    P99 = "p99"


class Properties3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    value: str | float | list[str] | list[float] | None = None
    operator: str | None = None
    type: str | None = None


class Properties4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Type2
    values: list[Value]


class Properties5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Type2
    values: list[Value]


class Series(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str
    """
    A display name
    """
    math: Math | None = None
    math_property: str | None = None
    properties: list[Properties3 | Properties4] | Properties5 | None = None
    kind: Literal["EventsNode"] = "EventsNode"
    event: str | None = None
    limit: float | None = None


class Display(StrEnum):
    ACTIONS_LINE_GRAPH = "ActionsLineGraph"
    ACTIONS_TABLE = "ActionsTable"
    ACTIONS_PIE = "ActionsPie"
    ACTIONS_BAR = "ActionsBar"
    ACTIONS_BAR_VALUE = "ActionsBarValue"
    WORLD_MAP = "WorldMap"
    BOLD_NUMBER = "BoldNumber"


class TrendsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    display: Display | None = Display.ACTIONS_LINE_GRAPH
    showLegend: bool | None = False


class BreakdownType(StrEnum):
    PERSON = "person"
    EVENT = "event"


class BreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_type: BreakdownType | None = BreakdownType.EVENT
    breakdown_limit: float | None = None
    breakdown: str | float | list[str | float] | None = None


class CompareFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: bool | None = False
    compare_to: str | None = None


class Source(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    properties: list[Properties | Properties1] | Properties2 | None = []
    kind: Literal["TrendsQuery"] = "TrendsQuery"
    interval: Interval | None = Interval.DAY
    series: list[Series]
    trendsFilter: TrendsFilter | None = None
    breakdownFilter: BreakdownFilter | None = None
    compareFilter: CompareFilter | None = None
    conversionGoal: Any = None


class Properties6(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    value: str | float | list[str] | list[float] | None = None
    operator: str | None = None
    type: str | None = None


class Properties7(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Type2
    values: list[Value]


class Properties8(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Type2
    values: list[Value]


class Properties9(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    value: str | float | list[str] | list[float] | None = None
    operator: str | None = None
    type: str | None = None


class Properties10(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Type2
    values: list[Value]


class Properties11(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Type2
    values: list[Value]


class Series1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str
    """
    A display name
    """
    math: Math | None = None
    math_property: str | None = None
    properties: list[Properties9 | Properties10] | Properties11 | None = None
    kind: Literal["EventsNode"] = "EventsNode"
    event: str | None = None
    limit: float | None = None


class Layout(StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class BreakdownAttributionType(StrEnum):
    FIRST_TOUCH = "first_touch"
    LAST_TOUCH = "last_touch"
    ALL_EVENTS = "all_events"


class FunnelOrderType(StrEnum):
    ORDERED = "ordered"
    UNORDERED = "unordered"
    STRICT = "strict"


class FunnelVizType(StrEnum):
    STEPS = "steps"
    TIME_TO_CONVERT = "time_to_convert"
    TRENDS = "trends"


class FunnelWindowIntervalUnit(StrEnum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class FunnelStepReference(StrEnum):
    TOTAL = "total"
    PREVIOUS = "previous"


class FunnelsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    layout: Layout | None = None
    breakdownAttributionType: BreakdownAttributionType | None = None
    breakdownAttributionValue: float | None = None
    funnelToStep: float | None = None
    funnelFromStep: float | None = None
    funnelOrderType: FunnelOrderType | None = None
    funnelVizType: FunnelVizType | None = None
    funnelWindowInterval: float | None = 14
    funnelWindowIntervalUnit: FunnelWindowIntervalUnit | None = FunnelWindowIntervalUnit.DAY
    funnelStepReference: FunnelStepReference | None = None


class BreakdownFilter1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_type: BreakdownType | None = BreakdownType.EVENT
    breakdown_limit: float | None = None
    breakdown: str | float | list[str | float] | None = None


class Source1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    properties: list[Properties6 | Properties7] | Properties8 | None = []
    kind: Literal["FunnelsQuery"] = "FunnelsQuery"
    interval: Interval | None = Interval.DAY
    series: Annotated[list[Series1], Field(min_length=2)]
    funnelsFilter: FunnelsFilter | None = None
    breakdownFilter: BreakdownFilter1 | None = None


class Query2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["InsightVizNode"] = "InsightVizNode"
    source: Source | Source1


class Properties12(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    value: str | float | list[str] | list[float] | None = None
    operator: str | None = None
    type: str | None = None


class Properties13(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Type2
    values: list[Value]


class Filters2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    properties: list[Properties12 | Properties13] | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = None


class Source2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["HogQLQuery"] = "HogQLQuery"
    query: str
    filters: Filters2 | None = None


class Query3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["DataVisualizationNode"] = "DataVisualizationNode"
    source: Source2


class QueryRunInputSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    query: Query2 | Query3


class Type11(StrEnum):
    POPOVER = "popover"
    API = "api"
    WIDGET = "widget"
    EXTERNAL_SURVEY = "external_survey"


class DescriptionContentType(StrEnum):
    HTML = "html"
    TEXT = "text"


class Questions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["open"] = "open"


class Questions1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["link"] = "link"
    link: AnyUrl


class Display1(StrEnum):
    """
    Display format: 'number' shows numeric scale, 'emoji' shows emoji scale
    """

    NUMBER = "number"
    EMOJI = "emoji"


class Scale(float, Enum):
    """
    Rating scale can be one of 3, 5, or 7
    """

    NUMBER_3 = 3
    NUMBER_5 = 5
    NUMBER_7 = 7


class Branching(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["next_question"] = "next_question"


class Branching1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["end"] = "end"


class Branching2(BaseModel):
    """
    For rating questions: use sentiment keys based on scale thirds - negative (lower third), neutral (middle third), positive (upper third)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["response_based"] = "response_based"
    responseValues: dict[str, float | str]
    """
    Only include keys for responses that should branch to a specific question or 'end'. Omit keys for responses that should proceed to the next question (default behavior).
    """


class Branching3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["specific_question"] = "specific_question"
    index: float


class Questions2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["rating"] = "rating"
    display: Display1 | None = None
    """
    Display format: 'number' shows numeric scale, 'emoji' shows emoji scale
    """
    scale: Scale | None = None
    """
    Rating scale can be one of 3, 5, or 7
    """
    lowerBoundLabel: str | None = None
    """
    Label for the lowest rating (e.g., 'Very Poor')
    """
    upperBoundLabel: str | None = None
    """
    Label for the highest rating (e.g., 'Excellent')
    """
    branching: Branching | Branching1 | Branching2 | Branching3 | None = None


class Branching4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["next_question"] = "next_question"


class Branching5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["end"] = "end"


class Branching6(BaseModel):
    """
    For NPS rating questions: use sentiment keys based on score ranges - detractors (0-6), passives (7-8), promoters (9-10)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["response_based"] = "response_based"
    responseValues: dict[str, float | str]
    """
    Only include keys for responses that should branch to a specific question or 'end'. Omit keys for responses that should proceed to the next question (default behavior).
    """


class Branching7(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["specific_question"] = "specific_question"
    index: float


class Questions3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["rating"] = "rating"
    display: Literal["number"] = "number"
    """
    NPS questions always use numeric scale
    """
    scale: Literal[10] = 10
    """
    NPS questions always use 0-10 scale
    """
    lowerBoundLabel: str | None = None
    """
    Label for 0 rating (typically 'Not at all likely')
    """
    upperBoundLabel: str | None = None
    """
    Label for 10 rating (typically 'Extremely likely')
    """
    branching: Branching4 | Branching5 | Branching6 | Branching7 | None = None


class Choice(RootModel[str]):
    root: Annotated[str, Field(min_length=1)]


class Branching8(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["next_question"] = "next_question"


class Branching9(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["end"] = "end"


class Branching10(BaseModel):
    """
    For single choice questions: use choice indices as string keys ("0", "1", "2", etc.)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["response_based"] = "response_based"
    responseValues: dict[str, float | str]
    """
    Only include keys for responses that should branch to a specific question or 'end'. Omit keys for responses that should proceed to the next question (default behavior).
    """


class Branching11(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["specific_question"] = "specific_question"
    index: float


class Questions4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["single_choice"] = "single_choice"
    choices: Annotated[list[Choice], Field(max_length=20, min_length=2)]
    """
    Array of choice options. Choice indices (0, 1, 2, etc.) are used for branching logic
    """
    shuffleOptions: bool | None = None
    """
    Whether to randomize the order of choices for each respondent
    """
    hasOpenChoice: bool | None = None
    """
    Whether the last choice (typically 'Other', is an open text input question
    """
    branching: Branching8 | Branching9 | Branching10 | Branching11 | None = None


class Questions5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["multiple_choice"] = "multiple_choice"
    choices: Annotated[list[Choice], Field(max_length=20, min_length=2)]
    """
    Array of choice options. Multiple selections allowed. No branching logic supported.
    """
    shuffleOptions: bool | None = None
    """
    Whether to randomize the order of choices for each respondent
    """
    hasOpenChoice: bool | None = None
    """
    Whether the last choice (typically 'Other', is an open text input question
    """


class ThankYouMessageDescriptionContentType(StrEnum):
    HTML = "html"
    TEXT = "text"


class WidgetType(StrEnum):
    BUTTON = "button"
    TAB = "tab"
    SELECTOR = "selector"


class Appearance(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    backgroundColor: str | None = None
    submitButtonColor: str | None = None
    textColor: str | None = None
    submitButtonText: str | None = None
    submitButtonTextColor: str | None = None
    descriptionTextColor: str | None = None
    ratingButtonColor: str | None = None
    ratingButtonActiveColor: str | None = None
    ratingButtonHoverColor: str | None = None
    whiteLabel: bool | None = None
    autoDisappear: bool | None = None
    displayThankYouMessage: bool | None = None
    thankYouMessageHeader: str | None = None
    thankYouMessageDescription: str | None = None
    thankYouMessageDescriptionContentType: ThankYouMessageDescriptionContentType | None = None
    thankYouMessageCloseButtonText: str | None = None
    borderColor: str | None = None
    placeholder: str | None = None
    shuffleQuestions: bool | None = None
    surveyPopupDelaySeconds: float | None = None
    widgetType: WidgetType | None = None
    widgetSelector: str | None = None
    widgetLabel: str | None = None
    widgetColor: str | None = None
    fontFamily: str | None = None
    maxWidth: str | None = None
    zIndex: str | None = None
    disabledButtonOpacity: str | None = None
    boxPadding: str | None = None


class ResponsesLimit(RootModel[float]):
    root: Annotated[float, Field(gt=0.0)]
    """
    The maximum number of responses before automatically stopping the survey.
    """


class IterationCount(RootModel[float]):
    root: Annotated[float, Field(gt=0.0)]
    """
    For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule.
    """


class IterationFrequencyDays(RootModel[float]):
    root: Annotated[float, Field(gt=0.0, le=365.0)]
    """
    For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.
    """


class Property2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    value: str | float | bool | list[str] | list[float]
    operator: Operator | None = None


class Group2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    properties: list[Property2]
    rollout_percentage: float


class TargetingFlagFilters(BaseModel):
    """
    Target specific users based on their properties. Example: {groups: [{properties: [{key: 'email', value: ['@company.com'], operator: 'icontains'}], rollout_percentage: 100}]}
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    groups: list[Group2]


class SurveyCreateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[str, Field(min_length=1)]
    description: str | None = None
    type: Type11 | None = None
    questions: Annotated[
        list[Questions | Questions1 | Questions2 | Questions3 | Questions4 | Questions5],
        Field(min_length=1),
    ]
    appearance: Appearance | None = None
    start_date: datetime | None = None
    """
    Setting this will launch the survey immediately. Don't add a start_date unless explicitly requested to do so.
    """
    responses_limit: ResponsesLimit | None = None
    """
    The maximum number of responses before automatically stopping the survey.
    """
    iteration_count: IterationCount | None = None
    """
    For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule.
    """
    iteration_frequency_days: IterationFrequencyDays | None = None
    """
    For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.
    """
    enable_partial_responses: bool | None = None
    """
    When at least one question is answered, the response is stored (true). The response is stored when all questions are answered (false).
    """
    linked_flag_id: float | None = None
    """
    The feature flag linked to this survey
    """
    targeting_flag_filters: TargetingFlagFilters | None = None
    """
    Target specific users based on their properties. Example: {groups: [{properties: [{key: 'email', value: ['@company.com'], operator: 'icontains'}], rollout_percentage: 100}]}
    """


class SurveyDeleteSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    surveyId: str


class SurveyGetAllSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    limit: float | None = None
    offset: float | None = None
    search: str | None = None


class SurveyGetSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    surveyId: str


class SurveyGlobalStatsSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: datetime | None = None
    """
    Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
    """
    date_to: datetime | None = None
    """
    Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)
    """


class SurveyResponseCountsSchema(BaseModel):
    pass
    model_config = ConfigDict(
        extra="forbid",
    )


class SurveyStatsSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    survey_id: str
    date_from: datetime | None = None
    """
    Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
    """
    date_to: datetime | None = None
    """
    Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)
    """


class Questions6(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["open"] = "open"


class Questions7(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["link"] = "link"
    link: AnyUrl


class Branching12(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["next_question"] = "next_question"


class Branching13(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["end"] = "end"


class Branching14(BaseModel):
    """
    For rating questions: use sentiment keys based on scale thirds - negative (lower third), neutral (middle third), positive (upper third)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["response_based"] = "response_based"
    responseValues: dict[str, float | str]
    """
    Only include keys for responses that should branch to a specific question or 'end'. Omit keys for responses that should proceed to the next question (default behavior).
    """


class Branching15(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["specific_question"] = "specific_question"
    index: float


class Questions8(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["rating"] = "rating"
    display: Display1 | None = None
    """
    Display format: 'number' shows numeric scale, 'emoji' shows emoji scale
    """
    scale: Scale | None = None
    """
    Rating scale can be one of 3, 5, or 7
    """
    lowerBoundLabel: str | None = None
    """
    Label for the lowest rating (e.g., 'Very Poor')
    """
    upperBoundLabel: str | None = None
    """
    Label for the highest rating (e.g., 'Excellent')
    """
    branching: Branching12 | Branching13 | Branching14 | Branching15 | None = None


class Branching16(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["next_question"] = "next_question"


class Branching17(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["end"] = "end"


class Branching18(BaseModel):
    """
    For NPS rating questions: use sentiment keys based on score ranges - detractors (0-6), passives (7-8), promoters (9-10)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["response_based"] = "response_based"
    responseValues: dict[str, float | str]
    """
    Only include keys for responses that should branch to a specific question or 'end'. Omit keys for responses that should proceed to the next question (default behavior).
    """


class Branching19(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["specific_question"] = "specific_question"
    index: float


class Questions9(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["rating"] = "rating"
    display: Literal["number"] = "number"
    """
    NPS questions always use numeric scale
    """
    scale: Literal[10] = 10
    """
    NPS questions always use 0-10 scale
    """
    lowerBoundLabel: str | None = None
    """
    Label for 0 rating (typically 'Not at all likely')
    """
    upperBoundLabel: str | None = None
    """
    Label for 10 rating (typically 'Extremely likely')
    """
    branching: Branching16 | Branching17 | Branching18 | Branching19 | None = None


class Branching20(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["next_question"] = "next_question"


class Branching21(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["end"] = "end"


class Branching22(BaseModel):
    """
    For single choice questions: use choice indices as string keys ("0", "1", "2", etc.)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["response_based"] = "response_based"
    responseValues: dict[str, float | str]
    """
    Only include keys for responses that should branch to a specific question or 'end'. Omit keys for responses that should proceed to the next question (default behavior).
    """


class Branching23(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["specific_question"] = "specific_question"
    index: float


class Questions10(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["single_choice"] = "single_choice"
    choices: Annotated[list[Choice], Field(max_length=20, min_length=2)]
    """
    Array of choice options. Choice indices (0, 1, 2, etc.) are used for branching logic
    """
    shuffleOptions: bool | None = None
    """
    Whether to randomize the order of choices for each respondent
    """
    hasOpenChoice: bool | None = None
    """
    Whether the last choice (typically 'Other', is an open text input question
    """
    branching: Branching20 | Branching21 | Branching22 | Branching23 | None = None


class Questions11(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    question: str
    description: str | None = None
    descriptionContentType: DescriptionContentType | None = None
    optional: bool | None = None
    buttonText: str | None = None
    type: Literal["multiple_choice"] = "multiple_choice"
    choices: Annotated[list[Choice], Field(max_length=20, min_length=2)]
    """
    Array of choice options. Multiple selections allowed. No branching logic supported.
    """
    shuffleOptions: bool | None = None
    """
    Whether to randomize the order of choices for each respondent
    """
    hasOpenChoice: bool | None = None
    """
    Whether the last choice (typically 'Other', is an open text input question
    """


class UrlMatchType(StrEnum):
    """
    URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain)
    """

    REGEX = "regex"
    NOT_REGEX = "not_regex"
    EXACT = "exact"
    IS_NOT = "is_not"
    ICONTAINS = "icontains"
    NOT_ICONTAINS = "not_icontains"


class Value9(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str


class Events(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    repeatedActivation: bool | None = None
    """
    Whether to show the survey every time one of the events is triggered (true), or just once (false)
    """
    values: list[Value9] | None = None
    """
    Array of event names that trigger the survey
    """


class DeviceType(StrEnum):
    DESKTOP = "Desktop"
    MOBILE = "Mobile"
    TABLET = "Tablet"


class DeviceTypesMatchType(StrEnum):
    """
    URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain)
    """

    REGEX = "regex"
    NOT_REGEX = "not_regex"
    EXACT = "exact"
    IS_NOT = "is_not"
    ICONTAINS = "icontains"
    NOT_ICONTAINS = "not_icontains"


class Conditions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    url: str | None = None
    selector: str | None = None
    seenSurveyWaitPeriodInDays: float | None = None
    """
    Don't show this survey to users who saw any survey in the last x days.
    """
    urlMatchType: UrlMatchType | None = None
    """
    URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain)
    """
    events: Events | None = None
    deviceTypes: list[DeviceType] | None = None
    deviceTypesMatchType: DeviceTypesMatchType | None = None
    """
    URL/device matching types: 'regex' (matches regex pattern), 'not_regex' (does not match regex pattern), 'exact' (exact string match), 'is_not' (not exact match), 'icontains' (case-insensitive contains), 'not_icontains' (case-insensitive does not contain)
    """
    linkedFlagVariant: str | None = None
    """
    The variant of the feature flag linked to this survey
    """


class Appearance1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    backgroundColor: str | None = None
    submitButtonColor: str | None = None
    textColor: str | None = None
    submitButtonText: str | None = None
    submitButtonTextColor: str | None = None
    descriptionTextColor: str | None = None
    ratingButtonColor: str | None = None
    ratingButtonActiveColor: str | None = None
    ratingButtonHoverColor: str | None = None
    whiteLabel: bool | None = None
    autoDisappear: bool | None = None
    displayThankYouMessage: bool | None = None
    thankYouMessageHeader: str | None = None
    thankYouMessageDescription: str | None = None
    thankYouMessageDescriptionContentType: ThankYouMessageDescriptionContentType | None = None
    thankYouMessageCloseButtonText: str | None = None
    borderColor: str | None = None
    placeholder: str | None = None
    shuffleQuestions: bool | None = None
    surveyPopupDelaySeconds: float | None = None
    widgetType: WidgetType | None = None
    widgetSelector: str | None = None
    widgetLabel: str | None = None
    widgetColor: str | None = None
    fontFamily: str | None = None
    maxWidth: str | None = None
    zIndex: str | None = None
    disabledButtonOpacity: str | None = None
    boxPadding: str | None = None


class Schedule(StrEnum):
    """
    Survey scheduling behavior: 'once' = show once per user (default), 'recurring' = repeat based on iteration_count and iteration_frequency_days settings, 'always' = show every time conditions are met (mainly for widget surveys)
    """

    ONCE = "once"
    RECURRING = "recurring"
    ALWAYS = "always"


class Property3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    value: str | float | bool | list[str] | list[float]
    operator: Operator | None = None


class Group3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    properties: list[Property3]
    rollout_percentage: float


class TargetingFlagFilters1(BaseModel):
    """
    Target specific users based on their properties. Example: {groups: [{properties: [{key: 'email', value: ['@company.com'], operator: 'icontains'}], rollout_percentage: 50}]}
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    groups: list[Group3]


class SurveyUpdateSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[str | None, Field(min_length=1)] = None
    description: str | None = None
    type: Type11 | None = None
    questions: Annotated[
        list[Questions6 | Questions7 | Questions8 | Questions9 | Questions10 | Questions11] | None,
        Field(min_length=1),
    ] = None
    conditions: Conditions | None = None
    appearance: Appearance1 | None = None
    schedule: Schedule | None = None
    """
    Survey scheduling behavior: 'once' = show once per user (default), 'recurring' = repeat based on iteration_count and iteration_frequency_days settings, 'always' = show every time conditions are met (mainly for widget surveys)
    """
    start_date: datetime | None = None
    """
    When the survey should start being shown to users. Setting this will launch the survey
    """
    end_date: datetime | None = None
    """
    When the survey stopped being shown to users. Setting this will complete the survey.
    """
    archived: bool | None = None
    responses_limit: ResponsesLimit | None = None
    """
    The maximum number of responses before automatically stopping the survey.
    """
    iteration_count: IterationCount | None = None
    """
    For a recurring schedule, this field specifies the number of times the survey should be shown to the user. Use 1 for 'once every X days', higher numbers for multiple repetitions. Works together with iteration_frequency_days to determine the overall survey schedule.
    """
    iteration_frequency_days: IterationFrequencyDays | None = None
    """
    For a recurring schedule, this field specifies the interval in days between each survey instance shown to the user, used alongside iteration_count for precise scheduling.
    """
    enable_partial_responses: bool | None = None
    """
    When at least one question is answered, the response is stored (true). The response is stored when all questions are answered (false).
    """
    linked_flag_id: float | None = None
    """
    The feature flag to link to this survey
    """
    targeting_flag_id: float | None = None
    """
    An existing targeting flag to use for this survey
    """
    targeting_flag_filters: TargetingFlagFilters1 | None = None
    """
    Target specific users based on their properties. Example: {groups: [{properties: [{key: 'email', value: ['@company.com'], operator: 'icontains'}], rollout_percentage: 50}]}
    """
    remove_targeting_flag: bool | None = None
    """
    Set to true to completely remove all targeting filters from the survey, making it visible to all users (subject to other display conditions like URL matching).
    """
    surveyId: str
