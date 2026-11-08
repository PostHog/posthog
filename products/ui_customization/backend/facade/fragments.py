from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .enums import FragmentButtonVariant, FragmentIcon

FragmentLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60, pattern=r"^[^\x00]*$")
]


class FragmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Target = TypeVar("Target", bound=BaseModel)
Source = TypeVar("Source", bound=str)
Item = TypeVar("Item", bound=BaseModel)
Section = TypeVar("Section", bound=BaseModel)


class FragmentLink(FragmentModel, Generic[Target]):
    """A link to a target supported by the context."""

    type: Literal["link"]
    to: Target
    label: FragmentLabel | None = None
    icon: FragmentIcon | None = None


class FragmentButton(FragmentModel, Generic[Target]):
    """A button that opens a target supported by the context."""

    type: Literal["button"]
    to: Target
    label: FragmentLabel
    icon: FragmentIcon | None = None
    variant: FragmentButtonVariant = FragmentButtonVariant.OUTLINE


class FragmentMetric(FragmentModel):
    """An insight-backed metric. The context defines the supported insight semantics."""

    type: Literal["metric"]
    insight: str
    label: FragmentLabel = Field(description="Short name of the number, such as Signups.")


class FragmentList(FragmentModel, Generic[Source]):
    """A list populated from a source supported by the context."""

    type: Literal["list"]
    source: Source


class FragmentSection(FragmentModel, Generic[Item]):
    id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description=(
            "Stable ID in lowercase kebab case, unique in the layout. The section's open or closed state is kept "
            "by this ID, so keep the ID of an existing section when you move or rename it."
        ),
    )
    title: FragmentLabel | None = Field(
        default=None,
        description=(
            "Heading of the section. A section with a heading can be closed. A section without one shows its items "
            "in its place in the layout, with no heading."
        ),
    )
    icon: FragmentIcon | None = Field(default=None, description="Icon before the heading.")
    items: list[Item] = Field(min_length=1)


class FragmentLayout(FragmentModel, Generic[Section]):
    """Ordered sections of a UI fragment, with content defined by its context."""

    version: Literal[1] = 1
    sections: list[Section] = Field(min_length=1)
