from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from posthog.enums import LabeledStrEnum

from .fragments import (
    FragmentButton,
    FragmentLayout,
    FragmentLink,
    FragmentList,
    FragmentMetric,
    FragmentModel,
    FragmentSection,
)


# Analytics context content is person- or agent-authored: closed targets, no URLs, HTML, or colors.
class AnalyticsPage(LabeledStrEnum):
    ANALYTICS_ALL = "analytics_all", "View all"
    ANALYTICS_MINE = "analytics_mine", "My work"
    COLLECTIONS = "collections", "Collections"
    ALERTS = "alerts", "Alerts"
    SUBSCRIPTIONS = "subscriptions", "Subscriptions"
    PRODUCT_ANALYTICS = "product_analytics", "Product analytics"
    WEB_ANALYTICS = "web_analytics", "Web analytics"
    SQL_EDITOR = "sql_editor", "SQL editor"
    NEW_INSIGHT = "new_insight", "New insight"


class AnalyticsListSource(LabeledStrEnum):
    PINNED = "pinned", "Items the person pinned"
    RECENTS = "recents", "Items the person opened recently"
    BY_POSTHOG = "by_posthog", "Ready-made analytics by PostHog"


ANALYTICS_SHORT_ID_PATTERN = r"^[A-Za-z0-9]{1,12}$"
ANALYTICS_NOTEBOOK_SHORT_ID_PATTERN = r"^[A-Za-z0-9]{1,12}$"
MAX_ANALYTICS_SECTIONS = 10
MAX_ANALYTICS_SECTION_ITEMS = 12
MAX_ANALYTICS_ITEMS = 30
MAX_ANALYTICS_METRICS = 4


class AnalyticsPageTarget(FragmentModel):
    """A PostHog page. It has its own label and icon."""

    kind: Literal["page"]
    page: AnalyticsPage


class AnalyticsInsightTarget(FragmentModel):
    kind: Literal["insight"]
    short_id: str = Field(
        pattern=ANALYTICS_SHORT_ID_PATTERN, description="The insight's short ID, as in /insights/<short_id>."
    )


class AnalyticsDashboardTarget(FragmentModel):
    kind: Literal["dashboard"]
    id: int = Field(ge=1, description="The dashboard's numeric ID.")


class AnalyticsNotebookTarget(FragmentModel):
    kind: Literal["notebook"]
    short_id: str = Field(
        pattern=ANALYTICS_NOTEBOOK_SHORT_ID_PATTERN, description="The notebook's short ID, as in /notebooks/<short_id>."
    )


AnalyticsTarget = Annotated[
    AnalyticsPageTarget | AnalyticsInsightTarget | AnalyticsDashboardTarget | AnalyticsNotebookTarget,
    Field(discriminator="kind", description="What the item opens. Only pages and objects of this project."),
]


class AnalyticsFragmentLink(FragmentLink[AnalyticsTarget]):
    """A link to an Analytics page or a project object. Object links require a label; pages supply their own label and icon."""

    @model_validator(mode="after")
    def _object_links_have_a_label(self) -> Self:
        if self.label is None and not isinstance(self.to, AnalyticsPageTarget):
            raise ValueError("A link to an insight, dashboard or notebook needs a label.")
        return self


class AnalyticsFragmentButton(FragmentButton[AnalyticsTarget]):
    """A button that opens an Analytics page or a project object."""


class AnalyticsFragmentMetric(FragmentMetric):
    """The latest value of a trends insight, with a sparkline of its first series. Opens the insight."""

    insight: str = Field(pattern=ANALYTICS_SHORT_ID_PATTERN, description="Short ID of a trends insight.")


class AnalyticsFragmentList(FragmentList[AnalyticsListSource]):
    """A list of pinned, recent, or built-in Analytics items."""


AnalyticsFragmentItem = Annotated[
    AnalyticsFragmentLink | AnalyticsFragmentButton | AnalyticsFragmentMetric | AnalyticsFragmentList,
    Field(discriminator="type"),
]


class AnalyticsFragmentSection(FragmentSection[AnalyticsFragmentItem]):
    items: list[AnalyticsFragmentItem] = Field(min_length=1, max_length=MAX_ANALYTICS_SECTION_ITEMS)


class AnalyticsFragmentLayout(FragmentLayout[AnalyticsFragmentSection]):
    """The Analytics context's fragment. A section with no items to show is hidden."""

    sections: list[AnalyticsFragmentSection] = Field(
        min_length=1,
        max_length=MAX_ANALYTICS_SECTIONS,
        description=(
            f"Use at most {MAX_ANALYTICS_ITEMS} items across all sections, including at most "
            f"{MAX_ANALYTICS_METRICS} metrics. Each built-in list counts as one item. "
            "Section IDs must be unique. Each list source can appear only once in the layout."
        ),
    )

    @model_validator(mode="after")
    def _ids_and_lists_are_unique(self) -> Self:
        ids = [section.id for section in self.sections]
        if len(set(ids)) != len(ids):
            raise ValueError("Each section needs its own id.")
        items = [item for section in self.sections for item in section.items]
        if len(items) > MAX_ANALYTICS_ITEMS:
            raise ValueError(
                f"Show at most {MAX_ANALYTICS_ITEMS} items across all sections. Remove some items and try again."
            )
        sources = [item.source for item in items if isinstance(item, AnalyticsFragmentList)]
        if len(set(sources)) != len(sources):
            raise ValueError("Each list source can show once.")
        if sum(isinstance(item, AnalyticsFragmentMetric) for item in items) > MAX_ANALYTICS_METRICS:
            raise ValueError(f"Show at most {MAX_ANALYTICS_METRICS} metrics.")
        return self
