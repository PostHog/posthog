from collections import defaultdict
from dataclasses import replace
from uuid import UUID

from posthog.dataclasses import frozen

from products.notebooks.backend.facade.contracts import AppWidgetSlot
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import NotebookNodeRun, NotebookWidgetInstance
from products.notebooks.backend.sql_v2_state import extract_cells, get_dataframe_owners
from products.notebooks.backend.util import _parse_markdown_component_props, iter_markdown_blocks
from products.notebooks.backend.widgets import widget_node_ids, widget_source_name


@frozen
class ApprovedWidgetSource:
    query: str
    slots: list[AppWidgetSlot]


def widget_source_slots(
    team_id: int, notebook_id: UUID, markdown: str, displayed: set[str]
) -> dict[str, list[AppWidgetSlot]]:
    content = build_markdown_notebook_content(markdown)
    visible_widgets = displayed & widget_node_ids(content)
    if not visible_widgets:
        return {}
    cells = extract_cells(content)
    owners = get_dataframe_owners(cells)
    native_sql = {
        cell.node_id for cell in cells if cell.cell_type == "sql" and not cell.connection_id and not cell.send_raw_query
    }
    instances = (
        NotebookWidgetInstance.objects.for_team(team_id)
        .filter(notebook_id=notebook_id, node_id__in=visible_widgets)
        .select_related("pinned_version", "widget__current_version")
    )
    by_node: dict[str, list[AppWidgetSlot]] = defaultdict(list)
    for instance in instances:
        version = instance.pinned_version or instance.widget.current_version
        if version is None:
            continue
        for item in version.input_contract:
            if isinstance(item, dict) and isinstance(item.get("slot"), str):
                node_id = owners.get(widget_source_name(instance, item))
                if node_id is not None and node_id in native_sql:
                    by_node[node_id].append(
                        AppWidgetSlot(node_id=instance.node_id, version_id=version.id, slot=item["slot"])
                    )
    return by_node


def approved_widget_sources(
    team_id: int, notebook_id: UUID, markdown: str, slots: dict[str, list[AppWidgetSlot]]
) -> dict[str, ApprovedWidgetSource]:
    if not slots:
        return {}
    pinned = {}
    for block in iter_markdown_blocks(markdown, max_prose_blocks=0):
        if block.tag_name == "SQLV2" and block.node_id in slots:
            run_id = _parse_markdown_component_props(block.source).get("runId")
            if isinstance(run_id, str):
                try:
                    pinned[UUID(run_id)] = block.node_id
                except ValueError:
                    continue
    runs = (
        NotebookNodeRun.objects.for_team(team_id)
        .filter(
            notebook_id=notebook_id,
            id__in=pinned,
            status=NotebookNodeRun.Status.DONE,
            node_type=NotebookNodeRun.NodeType.HOGQL,
            connection_id__isnull=True,
            send_raw_query=False,
        )
        .only("id", "node_id", "code")
    )
    return {
        run.node_id: ApprovedWidgetSource(
            query=run.code, slots=[replace(slot, run_id=run.id) for slot in slots[run.node_id]]
        )
        for run in runs
        if pinned[run.id] == run.node_id
    }
