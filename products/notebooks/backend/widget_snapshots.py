import copy
import json
import time
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from django.http import Http404

from posthog.models import User

from products.notebooks.backend.models import Notebook, NotebookNodeRun, NotebookRun, NotebookWidgetSnapshot
from products.notebooks.backend.sql_v2_direct import sync_direct_run
from products.notebooks.backend.widgets import (
    MAX_FRAME_PAGE_ROWS,
    MAX_FRAME_TOTAL_ROWS,
    WidgetConflictError,
    WidgetError,
    _bounded_rows,
    _dataframe_owners,
    _get_instance_and_version,
    _security_review_state,
    read_widget_frame,
)

MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
SNAPSHOT_CAPTURE_SECONDS = 30


class WidgetSnapshots:
    def __init__(self, notebook: Notebook, authorize_run: Callable[[NotebookNodeRun], None]) -> None:
        self.notebook = notebook
        self.authorize_run = authorize_run

    def capture(
        self,
        node_id: str,
        version_id: UUID,
        notebook_run_id: UUID | None = None,
        previous_snapshot_id: UUID | None = None,
    ) -> NotebookWidgetSnapshot:
        instance, version = _get_instance_and_version(self.notebook, node_id, version_id)
        bindings = copy.deepcopy(instance.input_bindings)
        if previous_snapshot_id is not None:
            previous = self.get(previous_snapshot_id)
            if previous.node_id != node_id or previous.version_id != version_id or previous.input_bindings != bindings:
                raise WidgetConflictError(
                    "The widget's inputs changed. Add it to the dashboard again to use its new inputs.",
                    "snapshot_inputs_changed",
                )
        owners = _dataframe_owners(self.notebook)
        runs = NotebookNodeRun.objects.for_team(self.notebook.team_id).filter(
            notebook=self.notebook, status=NotebookNodeRun.Status.DONE
        )
        if notebook_run_id is not None:
            completed = NotebookRun.objects.for_team(self.notebook.team_id).filter(
                notebook=self.notebook, id=notebook_run_id, status=NotebookRun.Status.DONE
            )
            if not completed.exists():
                raise WidgetConflictError("Wait for the notebook to finish before saving its results.", "run_not_ready")
            runs = runs.filter(notebook_run_id=notebook_run_id)
        frames: dict[str, Any] = {}
        source_runs: dict[str, str] = {}
        deadline = time.monotonic() + SNAPSHOT_CAPTURE_SECONDS
        size = 0
        for contract in version.input_contract:
            slot = contract["slot"]
            binding = bindings.get(slot, {})
            source = binding.get("source") or contract.get("sourceName") or slot
            run = runs.filter(node_id=owners.get(source)).order_by("-created_at").first()
            if run is None:
                raise WidgetConflictError(
                    f'Run the cell that creates "{source}" before adding this widget.', "frame_not_ready"
                )
            self.authorize_run(run)
            # Read the producer's result, since collaborators have separate kernels.
            producer = User.objects.filter(id=run.user_id).first() if run.user_id else None
            first = read_widget_frame(
                notebook=self.notebook,
                node_id=node_id,
                frame_name=slot,
                authorize_run=self.authorize_run,
                user=producer,
                version_id=version_id,
                run_id=run.id,
                limit=1,
            ).frame
            first["runId"] = str(run.id)
            rows = list(cast(list[list[object]], first["rows"]))
            target = min(cast(int, first["totalRowCount"]), MAX_FRAME_TOTAL_ROWS)
            preview = run.envelope.get("first_page", [])
            cached_rows = preview if len(preview) >= target else sync_direct_run(run)
            if cached_rows is None and run.node_type == NotebookNodeRun.NodeType.HOGQL:
                # Kernel HogQL paging re-executes the query and could mix rows from different results.
                raise WidgetConflictError(
                    "The SQL results expired. Run the notebook and try again.", "snapshot_results_expired"
                )
            while len(rows) < target:
                if time.monotonic() >= deadline:
                    raise WidgetConflictError(
                        "Saving the results took too long. Reduce the dataframe size and try again.", "snapshot_timeout"
                    )
                if cached_rows is not None:
                    page = _bounded_rows(
                        name=slot,
                        run_id=run.id,
                        columns=cast(list[dict[str, str]], first["columns"]),
                        candidates=cached_rows[len(rows) : len(rows) + MAX_FRAME_PAGE_ROWS],
                        total_row_count=cast(int, first["totalRowCount"]),
                        offset=len(rows),
                    )
                else:
                    page = read_widget_frame(
                        notebook=self.notebook,
                        node_id=node_id,
                        frame_name=slot,
                        authorize_run=self.authorize_run,
                        user=producer,
                        version_id=version_id,
                        run_id=run.id,
                        offset=len(rows),
                        limit=MAX_FRAME_PAGE_ROWS,
                    ).frame
                if not page["rows"]:
                    raise WidgetConflictError(
                        "Some results are no longer available. Run the notebook and try again.", "snapshot_incomplete"
                    )
                if page["totalRowCount"] != first["totalRowCount"]:
                    raise WidgetConflictError(
                        "The dataframe changed while saving. Run the notebook and try again.",
                        "snapshot_results_changed",
                    )
                rows.extend(cast(list[list[object]], page["rows"])[: target - len(rows)])
                if len(json.dumps(rows).encode()) + size > MAX_SNAPSHOT_BYTES:
                    raise WidgetError(
                        "Widget results must fit within 8 MiB. Reduce the dataframe size and try again.",
                        "snapshot_too_large",
                    )
            frame = {**first, "rows": rows, "includedRowCount": len(rows), "nextOffset": None}
            size += len(json.dumps(frame).encode())
            if size > MAX_SNAPSHOT_BYTES:
                raise WidgetError(
                    "Widget results must fit within 8 MiB. Reduce the dataframe size and try again.",
                    "snapshot_too_large",
                )
            frames[slot] = frame
            source_runs[slot] = str(run.id)
        instance.refresh_from_db(fields=["input_bindings"])
        if instance.input_bindings != bindings:
            raise WidgetConflictError(
                "The widget's inputs changed while saving. Try adding it again.", "snapshot_inputs_changed"
            )
        return NotebookWidgetSnapshot.objects.for_team(self.notebook.team_id).create(
            team_id=self.notebook.team_id,
            notebook=self.notebook,
            node_id=node_id,
            version=version,
            input_bindings=bindings,
            source_runs=source_runs,
            frames=frames,
        )

    def get(self, snapshot_id: UUID) -> NotebookWidgetSnapshot:
        snapshot = (
            NotebookWidgetSnapshot.objects.for_team(self.notebook.team_id)
            .filter(notebook=self.notebook, id=snapshot_id)
            .select_related("version", "version__widget")
            .defer("frames")
            .first()
        )
        if snapshot is None:
            raise Http404()
        run_ids = set(snapshot.source_runs.values())
        runs = list(
            NotebookNodeRun.objects.for_team(self.notebook.team_id)
            .filter(notebook=self.notebook, id__in=run_ids)
            .defer("envelope", "code")
        )
        if len(runs) != len(run_ids):
            raise WidgetConflictError(
                "The source results were deleted. Refresh this widget from the notebook.", "snapshot_source_missing"
            )
        for run in runs:
            self.authorize_run(run)
        return snapshot

    def describe(self, snapshot: NotebookWidgetSnapshot) -> dict[str, Any]:
        from products.canvas.backend import (
            notebook_integration as canvas_facade,  # noqa: PLC0415 — keeps Canvas off startup
        )

        try:
            versions = canvas_facade.list_notebook_canvas_versions(
                team_id=self.notebook.team_id,
                canvas_id=snapshot.version.widget.canvas_id,
                version_ids=[snapshot.version.canvas_source_version_id],
            )
        except canvas_facade.NotebookCanvasNotFoundError:
            versions = []
        artifact = next(iter(versions), None)
        return {
            "id": snapshot.id,
            "node_id": snapshot.node_id,
            "version_id": snapshot.version_id,
            "created_at": snapshot.created_at,
            "frame_names": list(snapshot.source_runs),
            "input_bindings": snapshot.input_bindings,
            "input_contract": snapshot.version.input_contract,
            "artifact_url": artifact.artifact_url if artifact else None,
            "build_hash": artifact.build_hash if artifact else None,
            "security_review": _security_review_state(snapshot.version),
        }

    def read_frame(self, snapshot: NotebookWidgetSnapshot, name: str, offset: int, limit: int) -> dict[str, Any]:
        if name not in snapshot.source_runs:
            raise WidgetError("This dataframe is not available to this widget.", "frame_not_allowed")
        frame = snapshot.frames[name]
        page = _bounded_rows(
            name=name,
            run_id=UUID(frame["runId"]),
            columns=frame["columns"],
            candidates=frame["rows"][offset : offset + min(limit, MAX_FRAME_PAGE_ROWS)],
            total_row_count=frame["totalRowCount"],
            offset=offset,
        )
        end = offset + len(cast(list[list[object]], page["rows"]))
        return {
            **page,
            "nextOffset": end if end < len(frame["rows"]) else None,
            "truncated": end < frame["totalRowCount"],
        }
