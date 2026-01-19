import pytest

from pydantic import ValidationError

from products.llm_analytics.backend.summarization.llm.schema import (
    InterestingNote,
    SummarizationResponse,
    SummaryBullet,
)


class TestSummaryBullet:
    def test_valid_bullet(self):
        bullet = SummaryBullet(text="User greeted the assistant", line_refs="L5")
        assert bullet.text == "User greeted the assistant"
        assert bullet.line_refs == "L5"

    def test_line_refs_range(self):
        bullet = SummaryBullet(text="Multi-turn conversation", line_refs="L10-15")
        assert bullet.line_refs == "L10-15"

    def test_missing_text_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            SummaryBullet(line_refs="L5")  # type: ignore[call-arg]
        assert "text" in str(exc_info.value)

    def test_missing_line_refs_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            SummaryBullet(text="Some text")  # type: ignore[call-arg]
        assert "line_refs" in str(exc_info.value)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError) as exc_info:
            SummaryBullet(text="Some text", line_refs="L5", extra_field="not allowed")  # type: ignore[call-arg]
        assert "extra_field" in str(exc_info.value).lower() or "extra" in str(exc_info.value).lower()


class TestInterestingNote:
    def test_valid_note_with_line_ref(self):
        note = InterestingNote(text="Error occurred during API call", line_refs="L45")
        assert note.text == "Error occurred during API call"
        assert note.line_refs == "L45"

    def test_valid_note_without_line_ref(self):
        note = InterestingNote(text="Overall successful execution", line_refs="")
        assert note.text == "Overall successful execution"
        assert note.line_refs == ""

    def test_missing_text_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            InterestingNote(line_refs="L5")  # type: ignore[call-arg]
        assert "text" in str(exc_info.value)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError) as exc_info:
            InterestingNote(text="Note", line_refs="L5", severity="high")  # type: ignore[call-arg]
        assert "severity" in str(exc_info.value).lower() or "extra" in str(exc_info.value).lower()


class TestSummarizationResponse:
    @pytest.fixture
    def valid_response_data(self):
        return {
            "title": "User Chat Session",
            "flow_diagram": "User → Assistant → Response",
            "summary_bullets": [
                {"text": "User asked a question", "line_refs": "L5"},
                {"text": "Assistant provided answer", "line_refs": "L15"},
            ],
            "interesting_notes": [],
        }

    def test_valid_minimal_response(self, valid_response_data):
        response = SummarizationResponse(**valid_response_data)
        assert response.title == "User Chat Session"
        assert response.flow_diagram == "User → Assistant → Response"
        assert len(response.summary_bullets) == 2
        assert len(response.interesting_notes) == 0

    def test_valid_detailed_response(self, valid_response_data):
        valid_response_data["interesting_notes"] = [
            {"text": "Fast response time", "line_refs": "L20"},
            {"text": "No errors encountered", "line_refs": ""},
        ]
        response = SummarizationResponse(**valid_response_data)
        assert len(response.interesting_notes) == 2

    def test_missing_title_raises(self, valid_response_data):
        del valid_response_data["title"]
        with pytest.raises(ValidationError) as exc_info:
            SummarizationResponse(**valid_response_data)
        assert "title" in str(exc_info.value)

    def test_missing_flow_diagram_raises(self, valid_response_data):
        del valid_response_data["flow_diagram"]
        with pytest.raises(ValidationError) as exc_info:
            SummarizationResponse(**valid_response_data)
        assert "flow_diagram" in str(exc_info.value)

    def test_missing_summary_bullets_raises(self, valid_response_data):
        del valid_response_data["summary_bullets"]
        with pytest.raises(ValidationError) as exc_info:
            SummarizationResponse(**valid_response_data)
        assert "summary_bullets" in str(exc_info.value)

    def test_empty_summary_bullets_allowed(self, valid_response_data):
        valid_response_data["summary_bullets"] = []
        response = SummarizationResponse(**valid_response_data)
        assert response.summary_bullets == []

    def test_extra_fields_forbidden(self, valid_response_data):
        valid_response_data["confidence_score"] = 0.95
        with pytest.raises(ValidationError) as exc_info:
            SummarizationResponse(**valid_response_data)
        assert "confidence_score" in str(exc_info.value).lower() or "extra" in str(exc_info.value).lower()

    def test_model_dump(self, valid_response_data):
        response = SummarizationResponse(**valid_response_data)
        dumped = response.model_dump()
        assert dumped == valid_response_data

    def test_model_json_schema_structure(self):
        schema = SummarizationResponse.model_json_schema()
        assert "title" in schema["properties"]
        assert "flow_diagram" in schema["properties"]
        assert "summary_bullets" in schema["properties"]
        assert "interesting_notes" in schema["properties"]
        assert schema["additionalProperties"] is False

    def test_json_serialization_roundtrip(self, valid_response_data):
        response = SummarizationResponse(**valid_response_data)
        json_str = response.model_dump_json()
        restored = SummarizationResponse.model_validate_json(json_str)
        assert restored == response
