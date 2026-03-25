from pydantic import BaseModel, Field


class PRInfo(BaseModel):
    number: int
    title: str
    author: str
    description: str = ""


class AffectedRoute(BaseModel):
    route_key: str = Field(description="Short identifier for the route (e.g., 'surveyWizard')")
    description: str = Field(description="One-line product description of what this page does")
    url_patterns: list[str] = Field(description="URL patterns this route serves (e.g., ['/surveys/guided/:id'])")


class PRManifest(BaseModel):
    pr: PRInfo
    affected_routes: list[AffectedRoute] = Field(default_factory=list)
    posthog_events: list[str] = Field(default_factory=list, description="PostHog event names found in changed code")
    feature_flag_keys: list[str] = Field(default_factory=list, description="Feature flag keys found in changed code")
