from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from posthog.dataclasses import frozen

from .enums import SidebarButtonVariant, SidebarIcon, SidebarListSource, SidebarPage

# The analytics sidebar: the layout of the Analytics pane in the new navigation. A person or their agent writes it,
# so every value is from a closed set: no URLs, no HTML, no colors, only PostHog pages and objects of the project.

SIDEBAR_SHORT_ID_PATTERN = r"^[A-Za-z0-9]{1,12}$"
SIDEBAR_NOTEBOOK_SHORT_ID_PATTERN = r"^[A-Za-z0-9]{1,12}$"
SIDEBAR_SECTION_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
MAX_SIDEBAR_SECTIONS = 10
MAX_SIDEBAR_SECTION_ITEMS = 12
MAX_SIDEBAR_ITEMS = 30
MAX_SIDEBAR_METRICS = 4

SidebarLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60, pattern=r"^[^\x00]*$")
]


class _SidebarModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SidebarPageTarget(_SidebarModel):
    """A PostHog page. It has its own label and icon."""

    kind: Literal["page"]
    page: SidebarPage


class SidebarInsightTarget(_SidebarModel):
    kind: Literal["insight"]
    short_id: str = Field(
        pattern=SIDEBAR_SHORT_ID_PATTERN, description="The insight's short ID, as in /insights/<short_id>."
    )


class SidebarDashboardTarget(_SidebarModel):
    kind: Literal["dashboard"]
    id: int = Field(ge=1, description="The dashboard's numeric ID.")


class SidebarNotebookTarget(_SidebarModel):
    kind: Literal["notebook"]
    short_id: str = Field(
        pattern=SIDEBAR_NOTEBOOK_SHORT_ID_PATTERN, description="The notebook's short ID, as in /notebooks/<short_id>."
    )


SidebarTarget = Annotated[
    SidebarPageTarget | SidebarInsightTarget | SidebarDashboardTarget | SidebarNotebookTarget,
    Field(discriminator="kind", description="What the item opens. Only pages and objects of this project."),
]


class SidebarLink(_SidebarModel):
    """A row that opens a page or an object."""

    type: Literal["link"]
    to: SidebarTarget
    label: SidebarLabel | None = Field(
        default=None, description="Text of the row. Leave it out for a page to use the page's name. Required otherwise."
    )
    icon: SidebarIcon | None = Field(default=None, description="Icon of the row. A page has its own icon.")

    @model_validator(mode="after")
    def _object_links_have_a_label(self) -> Self:
        if self.label is None and not isinstance(self.to, SidebarPageTarget):
            raise ValueError("A link to an insight, dashboard or notebook needs a label.")
        return self


class SidebarButton(_SidebarModel):
    """A button that opens a page or an object. Use it for an action, such as a new insight."""

    type: Literal["button"]
    to: SidebarTarget
    label: SidebarLabel
    icon: SidebarIcon | None = None
    variant: SidebarButtonVariant = SidebarButtonVariant.OUTLINE


class SidebarMetric(_SidebarModel):
    """The latest value of a trends insight, with a sparkline of its first series. Opens the insight."""

    type: Literal["metric"]
    insight: str = Field(pattern=SIDEBAR_SHORT_ID_PATTERN, description="Short ID of a trends insight.")
    label: SidebarLabel = Field(description="Short name of the number, such as Signups.")


class SidebarList(_SidebarModel):
    """A list that PostHog fills, such as the items the person pinned."""

    type: Literal["list"]
    source: SidebarListSource


SidebarItem = Annotated[
    SidebarLink | SidebarButton | SidebarMetric | SidebarList,
    Field(discriminator="type"),
]


class SidebarSection(_SidebarModel):
    id: str = Field(
        min_length=1,
        max_length=32,
        pattern=SIDEBAR_SECTION_ID_PATTERN,
        description="Stable ID in lowercase kebab case, unique in the layout. The section's open or closed state is kept by this ID.",
    )
    title: SidebarLabel | None = Field(
        default=None,
        description="Heading of the section. A section with a heading can be closed. Without one, its items show at the top.",
    )
    icon: SidebarIcon | None = Field(default=None, description="Icon before the heading.")
    items: list[SidebarItem] = Field(min_length=1, max_length=MAX_SIDEBAR_SECTION_ITEMS)


class AnalyticsSidebarLayout(_SidebarModel):
    """The sections of the Analytics pane, from top to bottom. A section with no items to show is hidden."""

    version: Literal[1] = 1
    sections: list[SidebarSection] = Field(min_length=1, max_length=MAX_SIDEBAR_SECTIONS)

    @model_validator(mode="after")
    def _ids_and_lists_are_unique(self) -> Self:
        ids = [section.id for section in self.sections]
        if len(set(ids)) != len(ids):
            raise ValueError("Each section needs its own id.")
        items = [item for section in self.sections for item in section.items]
        if len(items) > MAX_SIDEBAR_ITEMS:
            raise ValueError(
                f"Show at most {MAX_SIDEBAR_ITEMS} items across all sections. Remove some items and try again."
            )
        sources = [item.source for item in items if isinstance(item, SidebarList)]
        if len(set(sources)) != len(sources):
            raise ValueError("Each list source can show once.")
        if sum(isinstance(item, SidebarMetric) for item in items) > MAX_SIDEBAR_METRICS:
            raise ValueError(f"Show at most {MAX_SIDEBAR_METRICS} metrics.")
        return self


@frozen
class AnalyticsSidebar:
    layout: AnalyticsSidebarLayout
    customized: bool
