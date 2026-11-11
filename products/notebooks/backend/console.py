from typing import cast

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from posthog.admin.console.panels import Owner
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table, ToolOperation
from posthog.models.user import User
from posthog.utils import pluralize

from products.notebooks.backend.facade import api
from products.notebooks.backend.facade.contracts import MarkdownNotebookMigrationResult

DATA_TOOLS = Owner(name="Data tools", crest="data-tools")
TOOL_URL = "/admin/console/tools/notebook-markdown-migration/"
DEFAULT_BATCH_SIZE = 100
PREVIEW_CHARACTERS = 200


class ConvertNotebooksForm(forms.Form):
    team_id = forms.IntegerField(
        label="Team ID", required=False, min_value=1, help_text="Leave empty to convert notebooks of every team."
    )
    batch_size = forms.IntegerField(
        initial=DEFAULT_BATCH_SIZE,
        min_value=1,
        max_value=api.MAX_NOTEBOOK_MIGRATION_BATCH_SIZE,
        help_text="Pending notebooks converted in one run. Run it again for the next batch.",
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


def _scope(team_id: int | None) -> str:
    return f"team {team_id}" if team_id is not None else "all teams"


def _migrate(request: HttpRequest, form: forms.Form, dry_run: bool) -> MarkdownNotebookMigrationResult:
    return api.migrate_notebooks_to_markdown(
        user=cast(User, request.user),
        team_id=form.cleaned_data["team_id"],
        dry_run=dry_run,
        batch_size=form.cleaned_data["batch_size"],
    )


def preview_conversion(request: HttpRequest, form: forms.Form) -> Page:
    try:
        result = _migrate(request, form, dry_run=True)
    except ValueError as error:
        form.add_error("team_id", str(error))
        return Page(blocks=())
    if result.converted == 0 and result.errored == 0:
        form.add_error(None, f"No notebook of {_scope(result.team_id)} waits for conversion.")
        return Page(blocks=())

    summary = (
        f"Converts {pluralize(result.converted, 'notebook')} of the {result.pending_before} pending in "
        f"{_scope(result.team_id)}. {result.already_converted} of {result.total} are markdown already."
    )
    if result.converted > len(result.previews):
        summary += f" The table shows the first {len(result.previews)}."
    blocks: list[Notice | Table] = [
        Notice(text=summary),
        Table(
            columns=("Notebook", "Title", "Version", "Markdown"),
            rows=tuple(
                Row(
                    cells=(
                        Cell(text=preview.short_id, mono=True),
                        Cell(text=preview.title or "Untitled", muted=not preview.title),
                        Cell(text=str(preview.before_version)),
                        Cell(text=preview.markdown_preview[:PREVIEW_CHARACTERS], mono=True),
                    )
                )
                for preview in result.previews
            ),
        ),
    ]
    if result.errored:
        blocks.append(
            Notice(
                text=f"{pluralize(result.errored, 'notebook')} cannot be converted and stay as they are: "
                + "; ".join(result.errors)
            )
        )
    return Page(blocks=tuple(blocks))


def convert_notebooks(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    try:
        result = _migrate(request, form, dry_run=False)
    except ValueError as error:
        messages.error(request, str(error))
        return HttpResponse(status=400)
    messages.success(
        request,
        f"Converted {pluralize(result.converted, 'notebook')} to markdown. "
        f"{result.pending_after} still pending in {_scope(result.team_id)}.",
    )
    if result.skipped:
        messages.info(request, f"Skipped {pluralize(result.skipped, 'notebook')} that another change converted first.")
    if result.errored:
        messages.warning(
            request,
            f"{pluralize(result.errored, 'notebook')} could not be converted: " + "; ".join(result.errors),
        )
    # Back to the scope that just ran, so the next batch's form keeps the team.
    if result.team_id is None:
        return HttpResponseRedirect(TOOL_URL)
    return HttpResponseRedirect(f"{TOOL_URL}?team_id={result.team_id}")


def _team_id(request: HttpRequest) -> int | None:
    raw = request.GET.get("team_id", "").strip()
    return int(raw) if raw.isdigit() else None


@console.register_tool
class NotebookMarkdownMigrationTool(ConsoleTool):
    key = "notebook-markdown-migration"
    title = "Markdown notebook migration"
    owner = DATA_TOOLS
    group = "Data"
    description = "Converts rich notebooks to markdown notebooks in batches, after a preview."

    def page(self, request: HttpRequest) -> Page:
        team_id = _team_id(request)
        try:
            stats = api.get_markdown_notebook_migration_stats(team_id)
        except ValueError as error:
            return Page(blocks=(Notice(text=f"{error}.", link_text="All teams", href=TOOL_URL),))

        notice = (
            "Converts rich notebooks to the markdown notebook format. Each converted notebook gets a new version, "
            "open editors get the update, and the notebook history keeps the content from before. The counts "
            "include internal, account-linked and deleted notebooks."
        )
        return Page(
            blocks=(
                Notice(text=notice, link_text="All teams", href=TOOL_URL)
                if team_id is not None
                else Notice(text=notice),
                Table(
                    columns=("Scope", "Notebooks", "Markdown", "Pending"),
                    rows=(
                        Row(
                            cells=(
                                Cell(text=_scope(team_id).capitalize()),
                                Cell(text=f"{stats.total:,}"),
                                Cell(text=f"{stats.converted:,}"),
                                Cell(text=f"{stats.pending:,}"),
                            )
                        ),
                    ),
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        team_id = _team_id(request)
        return [
            ToolOperation(
                key="convert",
                label="Convert notebooks",
                handler=convert_notebooks,
                preview=preview_conversion,
                danger=True,
                description="Rewrites one batch of pending notebooks in the markdown format.",
                form_class=ConvertNotebooksForm,
                form_initial={"team_id": team_id} if team_id is not None else None,
                undo_hint=(
                    "PostHog Admin cannot convert a notebook back. Each notebook's history keeps its content from "
                    "before the conversion."
                ),
            )
        ]


# The old page fetched its stats/ and run/ JSON endpoints itself, so a bookmark of one lands on the tool page.
for old_path in (
    "admin/notebook-markdown-migration/",
    "admin/notebook-markdown-migration/stats/",
    "admin/notebook-markdown-migration/run/",
):
    console.register_moved_page(
        old_path=old_path,
        title="Markdown notebook migration",
        url="/admin/console/tools/notebook-markdown-migration/",
    )
