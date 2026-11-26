from collections.abc import Callable

from rest_framework.exceptions import ValidationError

from posthog.models import User

from products.notebooks.backend.facade.app_releases import run_app_cell
from products.notebooks.backend.facade.contracts import AppRefreshCheckTarget, AppRelease
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.sql_v2_state import extract_cells

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
    for cell in extract_cells(build_markdown_notebook_content(release.markdown)):
        if cell.node_id not in visible or not (
            cell.cell_type == "python" or (cell.cell_type == "sql" and cell.connection_id)
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
            run_app_cell(notebook.team_id, notebook.pk, owner, revision, node_id, {})
        except Exception:
            # A runtime error may include private stdout or rows. Persist only the published cell identifier.
            raise RuntimeCheckFailed(node_id, count) from None
