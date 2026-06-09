from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError

from products.signals.backend.artefact_schemas import (
    CodeDiff,
    CodeReference,
    LineReference,
    NoteArtefact,
    PushedBranch,
    TaskRunArtefact,
)


class TestArtefactSchemas(SimpleTestCase):
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

    def test_pushed_branch_requires_repo_and_branch(self):
        branch = PushedBranch(repository="PostHog/posthog", branch="fix/foo", base_branch="master")
        assert branch.head_sha is None
        with self.assertRaises(ValidationError):
            PushedBranch(repository="", branch="fix/foo")

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
