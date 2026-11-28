import json
import hashlib
import keyword
from collections.abc import Iterator
from contextlib import contextmanager
from typing import BinaryIO
from uuid import UUID

from django.db import IntegrityError, transaction

import requests
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.hogql.constants import MAX_SELECT_NOTEBOOK_MATERIALIZE_LIMIT

from posthog.models import User
from posthog.notebook_model_permissions import can_publish_notebook_model

from products.notebooks.backend.facade.contracts import NotebookCellLimitExceeded
from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun, NotebookRun
from products.notebooks.backend.notebook_run import PlannedCell, interrupt_notebook_run, plan_notebook_cells
from products.notebooks.backend.sql_v2 import _sandbox_auth_headers, kernel_server_secret, mint_command_token
from products.notebooks.backend.sql_v2_state import _DATAFRAME_NAME
from products.security.backend.facade.api import access_refused
from products.security.backend.facade.contracts import SubjectInput
from products.security.backend.facade.enums import Surface


def check_model_author(notebook: Notebook, user: User | None) -> User:
    if user is None or not user.is_active or notebook.deleted:
        raise PermissionDenied("An active project member and notebook are required to publish.")
    if access_refused(
        SubjectInput(email=user.email, user_uuid=str(user.uuid)), Surface.APP, call_site="notebook_warehouse_model"
    ):
        raise PermissionDenied("This account cannot publish notebook models.")
    if not can_publish_notebook_model(notebook, user_id=user.pk):
        raise PermissionDenied("Publishing a model requires notebook, warehouse, and query access.")
    return user


def model_plan(notebook: Notebook, output_cell: str) -> tuple[list[PlannedCell], str]:
    try:
        cells = plan_notebook_cells(notebook)
    except NotebookCellLimitExceeded as exc:
        raise ValidationError(str(exc)) from exc
    for index, cell in enumerate(cells):
        if cell["node_id"] != output_cell:
            continue
        plan = cells[: index + 1]
        if any(step["connection_id"] for step in plan):
            raise ValidationError("Use PostHog warehouse tables in a scheduled notebook model.")
        if len({step["node_id"] for step in plan}) != len(plan):
            raise ValidationError("Each model cell needs a unique cell ID.")
        names = [step["dataframe_name"] for step in plan if step["dataframe_name"]]
        if len(names) != len(set(names)):
            raise ValidationError("Give each model dataframe a distinct name.")
        if cell["cell_type"] == "sql":
            name = cell["dataframe_name"]
            if not _DATAFRAME_NAME.fullmatch(name) or keyword.iskeyword(name):
                raise ValidationError("Give the SQL output cell a dataframe name before publishing.")
            # A direct SQL run retains a preview. Reading its named frame uses the full query.
            export_id = f"export-{notebook.id.hex}"
            if any(step["node_id"] == export_id for step in plan):
                raise ValidationError("A cell ID conflicts with the SQL export cell.")
            plan.append(
                PlannedCell(
                    node_id=export_id,
                    cell_type="python",
                    dataframe_name="",
                    code=name,
                    connection_id=None,
                    send_raw_query=False,
                )
            )
        encoded = json.dumps([plan, notebook.variables or []], sort_keys=True, separators=(",", ":")).encode()
        return plan, hashlib.sha256(encoded).hexdigest()
    raise ValidationError("Choose a runnable SQL or Python output cell in this notebook.")


def notebook_model_digest(team_id: int, notebook_id: UUID, output_cell: str) -> str:
    notebook = Notebook.objects.get(team_id=team_id, id=notebook_id, deleted=False)
    return model_plan(notebook, output_cell)[1]


def authorize_model_publication(team_id: int, notebook_id: UUID, user: User | None) -> User:
    notebook = Notebook.objects.select_related("team").get(team_id=team_id, id=notebook_id, deleted=False)
    return check_model_author(notebook, user)


def prepare_model_run(
    team_id: int, notebook_id: UUID, output_cell: str, digest: str, user_id: int, run_id: UUID
) -> list[str] | None:
    notebook = Notebook.objects.select_related("team").get(team_id=team_id, id=notebook_id, deleted=False)
    user = User.objects.get(id=user_id, is_active=True)
    check_model_author(notebook, user)
    plan, current_digest = model_plan(notebook, output_cell)
    if current_digest != digest:
        raise ValidationError("The model cells or variables changed. Declare the model again to publish this version.")
    runs = NotebookRun.objects.for_team(team_id)
    try:
        with transaction.atomic():
            run, _ = runs.get_or_create(
                id=run_id,
                team_id=team_id,
                notebook=notebook,
                user=user,
                trigger=NotebookRun.Trigger.WAREHOUSE,
                defaults={"cell_plan": plan, "variables": notebook.variables or []},
            )
    except IntegrityError as exc:
        if getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None) == "unique_running_notebook_run":
            return None
        raise
    return [step["node_id"] for step in run.cell_plan]


def stop_model_run(team_id: int, run_id: UUID) -> None:
    run = (
        NotebookRun.objects.for_team(team_id)
        .select_related("notebook")
        .filter(id=run_id, trigger=NotebookRun.Trigger.WAREHOUSE, status=NotebookRun.Status.RUNNING)
        .first()
    )
    if run:
        interrupt_notebook_run(run.notebook, run)


@contextmanager
def open_model_output(team_id: int, notebook_id: UUID, run_id: UUID, max_bytes: int) -> Iterator[tuple[BinaryIO, int]]:
    run = (
        NotebookRun.objects.for_team(team_id)
        .select_related("notebook__team", "user")
        .get(id=run_id, notebook_id=notebook_id, trigger=NotebookRun.Trigger.WAREHOUSE)
    )
    if run.status != NotebookRun.Status.DONE:
        raise ValueError(f"Notebook run {run.id} {run.status} at cell {run.failed_node_id or 'unknown'}.")
    author = check_model_author(run.notebook, run.user)
    cell = NotebookNodeRun.objects.for_team(team_id).get(
        notebook_run=run,
        notebook_id=notebook_id,
        node_id=run.cell_plan[-1]["node_id"],
        status=NotebookNodeRun.Status.DONE,
    )
    if cell.result_id is None:
        raise ValueError(f"Cell {cell.node_id} did not return a dataframe.")
    runtime = (
        KernelRuntime.objects.filter(
            pk=cell.kernel_runtime_id,
            team_id=team_id,
            notebook_id=notebook_id,
            user_id=author.pk,
            status=KernelRuntime.Status.RUNNING,
        ).first()
        if cell.kernel_runtime_id is not None
        else None
    )
    if runtime is None or not runtime.server_url:
        raise ValueError("The output frame expired. Run the model again.")
    rows = int(cell.envelope["row_count"])
    if rows > MAX_SELECT_NOTEBOOK_MATERIALIZE_LIMIT:
        raise ValueError("The notebook output exceeds the warehouse model row limit.")
    token = mint_command_token(kernel_server_secret(str(runtime.id)), str(cell.id))
    with requests.post(
        f"{runtime.server_url.rstrip('/')}/result-parquet",
        json={
            "run_id": str(cell.id),
            "result_id": str(cell.result_id),
            "model_session": str(run.id),
            "max_rows": MAX_SELECT_NOTEBOOK_MATERIALIZE_LIMIT,
            "max_bytes": max_bytes,
        },
        headers=_sandbox_auth_headers(runtime.server_connect_token, token),
        stream=True,
        timeout=(10, 300),
        allow_redirects=False,
    ) as response:
        if response.status_code == 413:
            raise ValueError("The notebook output exceeds the warehouse model size limit.")
        if response.status_code != 200:
            raise ValueError(f"Could not read the full dataframe from notebook run {run.id}.")
        yield response.raw, rows
