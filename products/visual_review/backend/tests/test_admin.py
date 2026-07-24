"""Tests for visual_review admin behavior that isn't covered by Django itself."""

from typing import cast

import pytest

from django.forms.models import inlineformset_factory

from products.visual_review.backend.admin import RunSnapshotInline, _LimitedRunSnapshotFormSet
from products.visual_review.backend.models import Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestLimitedRunSnapshotFormSet:
    """`_LimitedRunSnapshotFormSet` caps inline rows at `LIMIT`. The cap has
    to happen *after* `BaseInlineFormSet.__init__` filters by parent FK —
    slicing on the inline's own `get_queryset` would crash Django with
    "Cannot filter a query once a slice has been taken." These tests pin
    that ordering and the per-parent isolation."""

    @pytest.fixture
    def repo(self, team):
        return Repo.objects.create(team_id=team.id, repo_external_id=1, repo_full_name="org/repo")

    @pytest.fixture
    def run(self, repo):
        return Run.objects.create(repo=repo, team_id=repo.team_id, commit_sha="aaa", branch="main")

    @pytest.fixture
    def other_run(self, repo):
        # Distinct branch keeps `(repo, branch, run_type)` unique against `run`.
        return Run.objects.create(repo=repo, team_id=repo.team_id, commit_sha="bbb", branch="feature")

    def _make_formset(self, parent_run: Run) -> _LimitedRunSnapshotFormSet:
        # `inlineformset_factory` is typed as returning `BaseInlineFormSet`
        # — its `formset=` kwarg picks the subclass at runtime but mypy
        # doesn't track that, so cast the result back.
        FormSet = cast(
            "type[_LimitedRunSnapshotFormSet]",
            inlineformset_factory(
                Run,
                RunSnapshot,
                formset=_LimitedRunSnapshotFormSet,
                fields=RunSnapshotInline.fields,
                extra=0,
                can_delete=False,
            ),
        )
        return FormSet(instance=parent_run)

    def test_caps_at_limit(self, run):
        for i in range(_LimitedRunSnapshotFormSet.LIMIT + 5):
            RunSnapshot.objects.create(run=run, team_id=run.team_id, identifier=f"snap-{i:03d}")

        formset = self._make_formset(run)

        assert formset.get_queryset().count() == _LimitedRunSnapshotFormSet.LIMIT

    def test_under_limit_returns_all(self, run):
        RunSnapshot.objects.create(run=run, team_id=run.team_id, identifier="only")

        formset = self._make_formset(run)

        assert formset.get_queryset().count() == 1

    def test_scopes_to_parent_run(self, run, other_run):
        # Critical regression: the cap must apply *per parent*, not globally.
        # If the formset sliced before Django filtered by FK, the other_run's
        # snapshots would leak in (or Django would crash on filter-after-slice).
        for i in range(5):
            RunSnapshot.objects.create(run=run, team_id=run.team_id, identifier=f"this-{i}")
        for i in range(5):
            RunSnapshot.objects.create(run=other_run, team_id=other_run.team_id, identifier=f"other-{i}")

        formset = self._make_formset(run)

        returned_run_ids = {s.run_id for s in formset.get_queryset()}
        assert returned_run_ids == {run.id}
