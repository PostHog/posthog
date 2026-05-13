import uuid

import pytest

from products.orchestra.backend.facade import api
from products.orchestra.backend.facade.contracts import ExecutionSummary
from products.orchestra.backend.models import Execution


@pytest.mark.django_db
class TestListExecutions:
    def test_returns_empty_list(self):
        result = api.list_executions()
        assert result == []

    def test_returns_executions(self):
        Execution.objects.create(
            execution_id="e1",
            run_id=uuid.uuid4(),
            execution_type="test_type",
            status="COMPLETED",
        )
        result = api.list_executions()
        assert len(result) == 1
        assert isinstance(result[0], ExecutionSummary)
        assert result[0].execution_id == "e1"

    def test_filters_by_status(self):
        Execution.objects.create(
            execution_id="e1",
            run_id=uuid.uuid4(),
            execution_type="test",
            status="RUNNING",
        )
        Execution.objects.create(
            execution_id="e2",
            run_id=uuid.uuid4(),
            execution_type="test",
            status="COMPLETED",
        )
        result = api.list_executions(status="COMPLETED")
        assert len(result) == 1
        assert result[0].execution_id == "e2"

    def test_pagination(self):
        for i in range(5):
            Execution.objects.create(
                execution_id=f"e{i}",
                run_id=uuid.uuid4(),
                execution_type="test",
                status="COMPLETED",
            )
        result = api.list_executions(limit=2, offset=0)
        assert len(result) == 2
