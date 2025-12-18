import pytest

from posthog.schema import HogLanguage, HogQLMetadata, HogQLQuery

from posthog.hogql import ast as hogql_ast

from products.notebooks.backend.api.notebook import NotebookViewSet
from products.notebooks.backend.models import Notebook


@pytest.mark.parametrize(
    "query, attribute_name",
    [
        (HogQLQuery(query="select {result}"), "values"),
        (HogQLMetadata(language=HogLanguage.HOG_QL, query="select {result}"), "globals"),
    ],
)
def test_kernel_placeholders_applied(monkeypatch, query, attribute_name):
    notebook = Notebook(short_id="test", team_id=1)
    kernel_placeholder = hogql_ast.Constant(value="from_kernel")
    existing_placeholder = hogql_ast.Constant(value="from_query")

    if attribute_name == "values":
        query.values = {"result": existing_placeholder}
    else:
        query.globals = {"result": existing_placeholder}

    monkeypatch.setattr(
        "products.notebooks.backend.api.notebook.notebook_kernel_service.get_hogql_placeholders",
        lambda _: {"result": kernel_placeholder},
    )

    NotebookViewSet()._inject_kernel_placeholders(notebook, query)

    injected_placeholders = getattr(query, attribute_name)
    assert injected_placeholders["result"] == existing_placeholder
