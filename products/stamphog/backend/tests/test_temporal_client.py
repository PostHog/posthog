import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from products.stamphog.backend.tasks.tasks import _start_review_workflow
from products.stamphog.backend.temporal.client import execute_stamphog_review_workflow


def test_review_workflow_start_attaches_to_a_live_run():
    review_run_id = str(uuid.uuid4())
    client = MagicMock()
    client.start_workflow = AsyncMock()

    with patch("products.stamphog.backend.temporal.client.async_connect", AsyncMock(return_value=client)):
        execute_stamphog_review_workflow(review_run_id=review_run_id, team_id=1)

    kwargs = client.start_workflow.await_args.kwargs
    assert kwargs["id"] == f"stamphog-review-{review_run_id}"
    # Without USE_EXISTING a duplicate delivery raises, and the tracing interceptor closes the
    # start span with an error before the caller can swallow it.
    assert kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.USE_EXISTING
    assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY


def test_start_review_workflow_swallows_a_closed_run_conflict():
    review_run_id = str(uuid.uuid4())
    conflict = WorkflowAlreadyStartedError(f"stamphog-review-{review_run_id}", "stamphog-review")

    with patch(
        "products.stamphog.backend.tasks.tasks.execute_stamphog_review_workflow", side_effect=conflict
    ) as execute:
        _start_review_workflow(review_run_id, team_id=1)

    execute.assert_called_once()


def test_start_review_workflow_propagates_a_genuine_start_failure():
    with patch(
        "products.stamphog.backend.tasks.tasks.execute_stamphog_review_workflow",
        side_effect=RuntimeError("Temporal unreachable"),
    ):
        with pytest.raises(RuntimeError):
            _start_review_workflow(str(uuid.uuid4()), team_id=1)
