from products.notebooks.backend.api.notebook import NotebookCollabSaveSerializer


def test_collab_save_serializer_allows_blank_title_and_text_content() -> None:
    serializer = NotebookCollabSaveSerializer(
        data={
            "client_id": "test-client",
            "version": 0,
            "steps": [{"stepType": "replace", "from": 0, "to": 0}],
            "content": {"type": "doc", "content": [{"type": "heading"}]},
            "text_content": "",
            "title": "",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["text_content"] == ""
    assert serializer.validated_data["title"] == ""
