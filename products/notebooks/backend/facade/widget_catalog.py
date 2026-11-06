import json
from functools import cache
from importlib import resources

from pydantic import BaseModel, ConfigDict, Field


class NotebookWidgetViewDefinition(BaseModel):
    name: str | None = None
    label: str
    description: str


class NotebookWidgetPropDefinition(BaseModel):
    description: str
    example: str | int


class NotebookWidgetDefinition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    label: str
    description: str
    node_type: str = Field(alias="nodeType")
    id_prop: str = Field(alias="idProp")
    id_description: str = Field(alias="idDescription")
    id_example: str | int = Field(alias="idExample")
    picker: str
    extra_props: dict[str, NotebookWidgetPropDefinition] = Field(default_factory=dict, alias="extraProps")
    default_view: NotebookWidgetViewDefinition = Field(alias="defaultView")
    views: dict[str, NotebookWidgetViewDefinition]


class NotebookWidgetCatalog(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    view_conventions: dict[str, str] = Field(alias="viewConventions")
    widgets: dict[str, NotebookWidgetDefinition]


@cache
def get_notebook_widget_catalog() -> NotebookWidgetCatalog:
    catalog_json = resources.files("products.notebooks").joinpath("notebook-widget-catalog.json").read_text()
    return NotebookWidgetCatalog.model_validate_json(catalog_json)


def format_notebook_widget_catalog_for_agents() -> str:
    widget_lines: list[str] = []
    for tag_name, widget in get_notebook_widget_catalog().widgets.items():
        default_view_name = widget.default_view.name or "detail"
        view_parts = [f"{default_view_name}: {widget.default_view.description}"]
        view_parts.extend(f"{view_name}: {view.description}" for view_name, view in widget.views.items())
        example_props = {widget.id_prop: widget.id_example}
        example_props.update({name: prop.example for name, prop in widget.extra_props.items()})
        example_props["view"] = "summary"
        markdown_props = " ".join(
            f"{name}={{{value}}}" if isinstance(value, int) else f"{name}={json.dumps(value)}"
            for name, value in example_props.items()
        )
        markdown_example = f"<{tag_name} {markdown_props} />"
        rich_text_example = json.dumps({"type": widget.node_type, "attrs": example_props}, separators=(",", ":"))
        identity = " ".join(
            [widget.id_description, *(f"{name}: {prop.description}" for name, prop in widget.extra_props.items())]
        )
        widget_lines.append(
            f"- {tag_name}: {widget.description} Identity: {identity} "
            f"Markdown: {markdown_example}. Rich text: {rich_text_example}. Views: {' '.join(view_parts)}"
        )

    return "\n".join(
        [
            "Notebook object widgets use shared view names. Use summary for compact supporting context, "
            "detail when the object is the main subject, and a specialized view when it directly answers the task.",
            "Filters are hidden by default. Add showFilters only when the reader should configure the widget. "
            "Results are shown by default. Add hideResults only when the result should be collapsed.",
            *widget_lines,
        ]
    )
