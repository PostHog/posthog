from collections.abc import Callable

from rest_framework.exceptions import ValidationError

from posthog.clickhouse.workload import Workload
from posthog.models import User

from products.notebooks.backend.facade.app_releases import run_app_cell
from products.notebooks.backend.facade.contracts import AppRefreshCheckTarget, AppRelease
from products.notebooks.backend.kernel_runtime import SCHEDULED_KERNEL_STARTS_PER_USER_PER_HOUR
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook, NotebookAppSchedule
from products.notebooks.backend.sql_v2_state import ambiguous_cell_ids, extract_cells

MAX_CHECKS = 3


def check_targets(release: AppRelease) -> list[AppRefreshCheckTarget]:
    if release.published_at is None:
        return []
    visible = {
        block["node_id"]: block
        for block in release.layout["blocks"]
        if block["kind"] == "cell" and block.get("display") != "source"
    }
    targets = []
    cells = extract_cells(build_markdown_notebook_content(release.markdown))
    ambiguous = ambiguous_cell_ids(cells)
    for cell in cells:
        if (
            cell.node_id in ambiguous
            or cell.node_id not in visible
            or not (cell.cell_type == "python" or (cell.cell_type == "sql" and cell.connection_id))
        ):
            continue
        targets.append(
            AppRefreshCheckTarget(
                node_id=cell.node_id,
                title=visible[cell.node_id].get("title") or cell.dataframe_name or cell.node_id,
                kind="Python" if cell.cell_type == "python" else "Connected SQL",
            )
        )
    return targets


def validate_checks(release: AppRelease, node_ids: list[str]) -> None:
    available = {target.node_id for target in check_targets(release)}
    if len(node_ids) > MAX_CHECKS or len(node_ids) != len(set(node_ids)) or not set(node_ids) <= available:
        raise ValidationError(f"Choose up to {MAX_CHECKS} different visible Python or connected SQL cells.")


def reserve_check_capacity(notebook: Notebook, owner: User, node_ids: list[str]) -> None:
    if not node_ids:
        return
    User.objects.select_for_update().get(pk=owner.pk)
    other_checks = (
        NotebookAppSchedule.objects.unscoped()
        .filter(owner=owner, enabled=True)
        .exclude(notebook=notebook)
        .values_list("checked_node_ids", flat=True)
    )
    if len(node_ids) + sum(len(checked) for checked in other_checks) > SCHEDULED_KERNEL_STARTS_PER_USER_PER_HOUR:
        raise ValidationError(
            f"Schedule up to {SCHEDULED_KERNEL_STARTS_PER_USER_PER_HOUR} private checks across your active schedules."
        )


class RuntimeCheckFailed(Exception):
    def __init__(self, node_id: str, completed: int):
        self.node_id = node_id
        self.completed = completed


def run_checks(
    notebook: Notebook, owner_id: int, revision: int, node_ids: list[str], authorize: Callable[[Notebook, User], None]
) -> None:
    for count, node_id in enumerate(node_ids):
        owner = User.objects.get(pk=owner_id)
        try:
            authorize(notebook, owner)
            run_app_cell(notebook.team_id, notebook.pk, owner, revision, node_id, {}, workload=Workload.OFFLINE)
        except Exception:
            # A runtime error may include private stdout or rows. Persist only the published cell identifier.
            raise RuntimeCheckFailed(node_id, count) from None
