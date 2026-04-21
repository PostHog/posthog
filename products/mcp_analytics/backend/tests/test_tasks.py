from products.mcp_analytics.backend.tasks import tasks


def test_tasks_module_imports() -> None:
    assert tasks is not None
