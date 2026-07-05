import uuid

from posthog.test.base import APIBaseTest

from products.notebooks.backend.facade import api as notebooks
from products.pulse.backend.models import Opportunity
from products.pulse.backend.temporal.research_workflow import _persist_notebook_id


class TestPersistNotebookId(APIBaseTest):
    def _opportunity(self) -> Opportunity:
        return Opportunity.objects.for_team(self.team.pk).create(
            team=self.team,
            kind=Opportunity.Kind.BUILD,
            status=Opportunity.Status.OPEN,
            title="Recover the signup drop",
            summary="s",
            fingerprint=f"build:{uuid.uuid4()}",
        )

    def _notebook(self, title: str) -> notebooks.contracts.NotebookData:
        return notebooks.create_notebook(self.team.id, title=title, content={"type": "doc", "content": []})

    def test_re_research_archives_the_superseded_notebook(self) -> None:
        opportunity = self._opportunity()
        first = self._notebook("First research")
        _persist_notebook_id(self.team.id, str(opportunity.id), first.id)

        second = self._notebook("Second research")
        _persist_notebook_id(self.team.id, str(opportunity.id), second.id)

        opportunity.refresh_from_db()
        assert opportunity.research_notebook_id == second.id
        # The superseded notebook is archived so it no longer lingers in the team's list, but the
        # row survives (soft delete) for anyone holding its link.
        assert notebooks.get_notebook(self.team.id, first.short_id, include_deleted=True) is not None
        assert notebooks.get_notebook(self.team.id, first.short_id) is None
        assert notebooks.get_notebook(self.team.id, second.short_id) is not None
