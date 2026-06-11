import json

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError

from products.signals.backend.artefact_schemas import (
    ARTEFACT_CONTENT_SCHEMAS,
    ArtefactContentValidationError,
    CodeDiff,
    CodeReference,
    Commit,
    LineReference,
    NoteArtefact,
    RepoSelection,
    TaskRunArtefact,
    validate_artefact_content,
)
from products.signals.backend.models import SignalReportArtefact
from products.tasks.backend.repo_selection import RepoSelectionResult


class TestArtefactSchemas(SimpleTestCase):
    def test_registry_covers_every_artefact_type_exactly(self):
        assert set(ARTEFACT_CONTENT_SCHEMAS.keys()) == set(SignalReportArtefact.ArtefactType.values)

    def test_repo_selection_mirror_stays_in_sync_with_tasks_model(self):
        # `RepoSelection` mirrors the tasks-product `RepoSelectionResult` (no cross-product import
        # from the schema module). If the tasks model grows a field, the mirror must follow.
        assert set(RepoSelection.model_fields) >= set(RepoSelectionResult.model_fields)

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

    def test_code_diff_round_trips(self):
        diff = CodeDiff(file_path="a.py", diff="@@ -1 +1 @@", relevance_note="why")
        assert diff.file_path == "a.py"

    def test_line_reference_defaults_contents_to_none(self):
        ref = LineReference(file_path="a.py", line=10, note="look here")
        assert ref.contents is None

    def test_line_reference_rejects_line_below_one(self):
        with self.assertRaises(ValidationError):
            LineReference(file_path="a.py", line=0, note="x")

    def test_commit_normalizes_sha_and_defaults_note(self):
        commit = Commit(repository="PostHog/posthog", branch="fix/foo", commit_sha="ABC123F", message="fix: foo")
        assert commit.commit_sha == "abc123f"
        assert commit.note is None

    @parameterized.expand(
        [
            ("too_short", "abc12"),
            ("not_hex", "zzzz9999"),
            ("traversal", "../etc/passwd"),
            ("blank", "   "),
        ]
    )
    def test_commit_rejects_invalid_sha(self, _name, sha):
        with self.assertRaises(ValidationError):
            Commit(repository="PostHog/posthog", branch="fix/foo", commit_sha=sha, message="fix: foo")

    @parameterized.expand([("repository",), ("branch",), ("message",)])
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
        ]
    )
    def test_accepts_valid_content_for_type(self, artefact_type, content):
        normalized = validate_artefact_content(artefact_type, content)
        assert json.loads(normalized) == content

    @parameterized.expand(
        [
            ("safety_judgment", {"choice": "definitely"}),
            ("actionability_judgment", {"explanation": "", "actionability": "nope", "already_addressed": False}),
            ("priority_judgment", {"explanation": "x", "priority": "P9"}),
            ("signal_finding", {"signal_id": "s1"}),
            ("repo_selection", {"reason": 5}),
            ("suggested_reviewers", [{"github_name": "no login"}]),
            ("note", {"note": "   "}),
            ("commit", {"repository": "PostHog/posthog", "branch": "b", "commit_sha": "nope", "message": "m"}),
            ("task_run", {"task_id": "t1", "product": "Not Safe!", "type": "research"}),
        ]
    )
    def test_rejects_invalid_content_for_type(self, artefact_type, content):
        with self.assertRaises(ArtefactContentValidationError):
            validate_artefact_content(artefact_type, content)

    def test_accepts_json_text_and_preserves_extra_keys(self):
        # Validation is a gate, not a rewrite — forward-compatible extra keys survive.
        text = json.dumps({"note": "hello", "future_field": 42})
        assert json.loads(validate_artefact_content("note", text)) == {"note": "hello", "future_field": 42}

    def test_rejects_unknown_type_and_malformed_json(self):
        with self.assertRaises(ArtefactContentValidationError):
            validate_artefact_content("pushed_branch", {"repository": "a/b", "branch": "c"})
        with self.assertRaises(ArtefactContentValidationError):
            validate_artefact_content("note", "{not json")
