import json

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import BaseModel, ValidationError

from products.signals.backend.artefact_schemas import (
    ARTEFACT_CONTENT_SCHEMAS,
    ArtefactContentValidationError,
    CodeReference,
    Commit,
    NoteArtefact,
    SummaryChange,
    TaskRunArtefact,
    TitleChange,
    artefact_type_for,
    parse_artefact_content,
)
from products.signals.backend.models import SignalReportArtefact


class TestArtefactSchemas(SimpleTestCase):
    def test_registry_covers_every_artefact_type_exactly(self):
        assert set(ARTEFACT_CONTENT_SCHEMAS.keys()) == set(SignalReportArtefact.ArtefactType.values)

    def test_code_reference_round_trips(self):
        ref = CodeReference(file_path="a.py", start_line=1, end_line=3, contents="x", relevance_note="why")
        assert ref.model_dump()["end_line"] == 3

    def test_code_reference_rejects_end_before_start(self):
        with self.assertRaises(ValidationError):
            CodeReference(file_path="a.py", start_line=5, end_line=2, contents="x", relevance_note="why")

    @parameterized.expand([("file_path",), ("contents",), ("relevance_note",)])
    def test_code_reference_rejects_blank_strings(self, field):
        kwargs = {"file_path": "a.py", "start_line": 1, "end_line": 2, "contents": "x", "relevance_note": "why"}
        kwargs[field] = "   "
        with self.assertRaises(ValidationError):
            CodeReference(**kwargs)

    @parameterized.expand(
        [
            ("line_too_long", {"contents": "x" * 1001}),
            ("too_many_lines", {"contents": "\n".join(["x"] * 21), "end_line": 21}),
            ("span_too_wide", {"end_line": 22}),
        ]
    )
    def test_code_reference_rejects_unbounded_contents(self, _name, overrides):
        kwargs = {"file_path": "a.py", "start_line": 1, "end_line": 2, "contents": "x\ny", "relevance_note": "why"}
        kwargs.update(overrides)
        with self.assertRaises(ValidationError):
            CodeReference(**kwargs)

    def test_code_reference_accepts_bounded_contents(self):
        ref = CodeReference(
            file_path="a.py",
            start_line=1,
            end_line=20,
            contents="\n".join(["x" * 1000] * 20),
            relevance_note="why",
        )
        assert ref.end_line == 20

    def test_commit_defaults_note_to_none(self):
        commit = Commit(repository="PostHog/posthog", branch="fix/foo", commit_sha="abc123f", message="fix: foo")
        assert commit.note is None

    @parameterized.expand([("repository",), ("branch",), ("commit_sha",), ("message",)])
    def test_commit_rejects_blank_strings(self, field):
        kwargs = {"repository": "PostHog/posthog", "branch": "fix/foo", "commit_sha": "abc123f", "message": "m"}
        kwargs[field] = "   "
        with self.assertRaises(ValidationError):
            Commit(**kwargs)

    def test_task_run_carries_product_and_type(self):
        artefact = TaskRunArtefact(task_id="abc", product="signals", type="research")
        assert artefact.product == "signals"
        assert artefact.type == "research"

    @parameterized.expand([("product",), ("type",)])
    def test_task_run_rejects_non_routing_safe_identifier(self, field):
        kwargs = {"task_id": "abc", "product": "signals", "type": "research"}
        kwargs[field] = "Not Safe!"
        with self.assertRaises(ValidationError):
            TaskRunArtefact(**kwargs)

    def test_note_rejects_blank(self):
        assert NoteArtefact(note="hello").note == "hello"
        with self.assertRaises(ValidationError):
            NoteArtefact(note="   ")

    def test_title_change_allows_null_old_title(self):
        # A report with no prior title (null) is a valid before-state for the first edit.
        change = TitleChange(new_title="A title")
        assert change.old_title is None
        assert change.new_title == "A title"

    def test_title_change_rejects_blank_new_title(self):
        with self.assertRaises(ValidationError):
            TitleChange(old_title="old", new_title="   ")

    def test_summary_change_rejects_blank_new_summary(self):
        with self.assertRaises(ValidationError):
            SummaryChange(old_summary="old", new_summary="   ")


class TestValidateArtefactContent(SimpleTestCase):
    @parameterized.expand(
        [
            ("safety_judgment", {"choice": True, "explanation": None}),
            (
                "actionability_judgment",
                {"explanation": "Looked at it.", "actionability": "not_actionable", "already_addressed": False},
            ),
            ("priority_judgment", {"explanation": "It is bad.", "priority": "P1"}),
            (
                "signal_finding",
                {"signal_id": "s1", "relevant_code_paths": ["a.py"], "data_queried": "none", "verified": True},
            ),
            ("repo_selection", {"repository": None, "reason": "no candidates"}),
            ("suggested_reviewers", [{"github_login": "octocat", "github_name": None, "relevant_commits": []}]),
            ("dismissal", {"reason": "not_a_bug", "note": None, "user_id": 1, "user_uuid": None}),
            ("video_segment", {"anything": "goes"}),
            ("note", {"note": "hello"}),
            (
                "commit",
                {"repository": "PostHog/posthog", "branch": "b", "commit_sha": "abc123f", "message": "fix: x"},
            ),
            ("task_run", {"task_id": "t1", "run_id": None, "product": "signals", "type": "implementation"}),
            ("title_change", {"old_title": "before", "new_title": "after"}),
            ("summary_change", {"old_summary": None, "new_summary": "after"}),
        ]
    )
    def test_accepts_valid_content_for_type(self, artefact_type, content):
        parsed = parse_artefact_content(artefact_type, content)
        assert artefact_type_for(parsed) == artefact_type
        # The typed model round-trips through its stored JSON representation.
        assert parse_artefact_content(artefact_type, parsed.model_dump_json()) == parsed

    @parameterized.expand(
        [
            ("safety_judgment", {"choice": "definitely"}),
            ("actionability_judgment", {"explanation": "", "actionability": "nope", "already_addressed": False}),
            ("priority_judgment", {"explanation": "x", "priority": "P9"}),
            ("signal_finding", {"signal_id": "s1"}),
            ("repo_selection", {"reason": 5}),
            ("suggested_reviewers", [{"github_name": "no login"}]),
            ("note", {"note": "   "}),
            ("commit", {"repository": "PostHog/posthog", "branch": "b", "commit_sha": "  ", "message": "m"}),
            ("task_run", {"task_id": "t1", "product": "Not Safe!", "type": "research"}),
        ]
    )
    def test_rejects_invalid_content_for_type(self, artefact_type, content):
        with self.assertRaises(ArtefactContentValidationError):
            parse_artefact_content(artefact_type, content)

    def test_parsing_normalizes_to_the_schema(self):
        # Parsing into the typed model is the boundary: unknown keys are not persisted, and
        # omitted optional fields are stored with their defaults.
        parsed = parse_artefact_content("note", json.dumps({"note": "hello", "future_field": 42}))
        assert json.loads(parsed.model_dump_json()) == {"note": "hello", "author": None}

    def test_rejects_unknown_type_and_malformed_json(self):
        with self.assertRaises(ArtefactContentValidationError):
            parse_artefact_content("pushed_branch", {"repository": "a/b", "branch": "c"})
        with self.assertRaises(ArtefactContentValidationError):
            parse_artefact_content("note", "{not json")

    def test_artefact_type_for_rejects_non_content_models(self):
        class NotAnArtefact(BaseModel):
            x: int = 1

        with self.assertRaises(ArtefactContentValidationError):
            artefact_type_for(NotAnArtefact())
