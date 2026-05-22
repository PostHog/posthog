import pytest

from products.notebooks.backend.api.notebook import NotebookCollabSaveSerializer


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
