from pydantic import BaseModel, Field


class RouteContext(BaseModel):
    route_key: str
    description: str = ""
    url_patterns: list[str] = Field(default_factory=list)
    pageviews_30d: int | None = None
    traffic_share: str | None = None
    unique_users_30d: int | None = None
    rage_clicks_30d: int | None = None
    top_errors: list[dict] = Field(default_factory=list)
    replay_url: str | None = None


class EventContext(BaseModel):
    name: str
    count: int = 0
    users: int = 0


class FlagContext(BaseModel):
    key: str
    active: bool | None = None
    rollout_percentage: float | None = None


class ExperimentContext(BaseModel):
    name: str
    status: str = ""
    url_match: str = ""


class AnnotationContext(BaseModel):
    date: str = ""
    content: str = ""


class PostHogContext(BaseModel):
    pr: dict = Field(default_factory=dict)
    app_total_pageviews_30d: int | None = None
    routes: list[RouteContext] = Field(default_factory=list)
    events: list[EventContext] = Field(default_factory=list)
    feature_flags: list[FlagContext] = Field(default_factory=list)
    experiments: list[ExperimentContext] = Field(default_factory=list)
    annotations: list[AnnotationContext] = Field(default_factory=list)
