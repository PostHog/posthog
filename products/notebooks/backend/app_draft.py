from uuid import UUID

from posthog.exceptions import Conflict

from products.notebooks.backend.facade.contracts import AppRelease
from products.notebooks.backend.markdown_collab import get_markdown_notebook_markdown
from products.notebooks.backend.models import Notebook


def draft_app_release(team_id: int, notebook_id: UUID, revision: int, layout: dict[str, object]) -> AppRelease:
    notebook = Notebook.objects.get(team_id=team_id, pk=notebook_id)
    return draft_release_from_notebook(notebook, revision, layout, get_markdown_notebook_markdown(notebook.content))


def draft_release_from_notebook(
    notebook: Notebook, revision: int, layout: dict[str, object], markdown: str | None
) -> AppRelease:
    if revision != notebook.version:
        raise Conflict("The notebook changed. Reopen the preview to load its latest sources.")
    return AppRelease(
        revision=revision,
        published_at=None,
        results_as_of=None,
        title=notebook.title or "",
        layout=layout,
        markdown=markdown or "",
        variables=notebook.variables or [],
        has_previous=False,
    )
