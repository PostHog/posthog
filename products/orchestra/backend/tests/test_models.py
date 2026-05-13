import uuid

import pytest

from products.orchestra.backend.models import Execution, Task


@pytest.mark.django_db
class TestExecution:
    def test_create_execution(self):
        execution = Execution.objects.create(
            execution_id="test-exec-1",
            run_id=uuid.uuid4(),
            execution_type="greeting_execution",
            step_queue="default",
            input={"name": "World"},
            status="RUNNING",
        )
        assert execution.execution_id == "test-exec-1"
        assert execution.status == "RUNNING"
        assert execution.started_at is not None
        assert execution.finished_at is None

    def test_unique_together_constraint(self):
        run_id = uuid.uuid4()
        Execution.objects.create(
            execution_id="test-exec-2",
            run_id=run_id,
            execution_type="test",
        )
        with pytest.raises(Exception):
            Execution.objects.create(
                execution_id="test-exec-2",
                run_id=run_id,
                execution_type="test",
            )


@pytest.mark.django_db
class TestTask:
    def test_create_task(self):
        task = Task.objects.create(
            task_queue="default",
            task_type="EXECUTION_TASK",
            execution_id="test-exec-1",
            run_id=uuid.uuid4(),
        )
        assert task.task_id is not None
        assert task.attempt == 1
        assert task.locked_by is None
