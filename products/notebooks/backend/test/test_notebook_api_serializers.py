import pytest

from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.presentation.views.notebook import (
    NotebookCollabSaveSerializer,
    NotebookMarkdownSaveSerializer,
)


@pytest.mark.parametrize(
    ("optional_payload", "expected_title"),
    [
        pytest.param({"text_content": "", "title": ""}, "", id="blank-title"),
        pytest.param({"text_content": ""}, None, id="omitted-title"),
    ],
)
def test_collab_save_serializer_handles_blank_and_omitted_title(
    optional_payload: dict[str, object], expected_title: str | None
) -> None:
    serializer = NotebookCollabSaveSerializer(
        data={
            "client_id": "test-client",
            "version": 0,
            "steps": [{"stepType": "replace", "from": 0, "to": 0}],
            "content": {"type": "doc", "content": [{"type": "heading"}]},
            **optional_payload,
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["text_content"] == ""
    if expected_title is None:
        assert "title" not in serializer.validated_data
    else:
        assert serializer.validated_data["title"] == expected_title


def test_markdown_save_serializer_clamps_overlong_title() -> None:
    # The title is derived from the document's first heading, so an overlong heading must clamp to the
    # varchar(256) column rather than fail the whole save with a StringDataRightTruncation.
    max_length = Notebook._meta.get_field("title").max_length
    assert max_length is not None
    serializer = NotebookMarkdownSaveSerializer(
        data={
            "client_id": "test-client",
            "version": 0,
            "content": build_markdown_notebook_content("# Heading"),
            "title": "a" * (max_length + 50),
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["title"] == "a" * max_length
