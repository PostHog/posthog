from django.test import SimpleTestCase

from parameterized import parameterized

from products.foundry.backend.presentation.serializers import CreateBetEventSerializer, RunConfigSerializer


class TestNodePayloadValidation(SimpleTestCase):
    """Node/knowledge event kinds validate their payload shape; other kinds are untouched."""

    @parameterized.expand(
        [
            ("node.spawned", {}, "node_id"),
            ("node.finished", {}, "node_id"),
            ("node.failed", {}, "node_id"),
            ("budget.exceeded", {"node_id": "root.0"}, "cap"),
            ("budget.exceeded", {"node_id": "root.0", "cap": "not-a-real-cap"}, "cap"),
            ("knowledge.published", {}, "repo"),
        ]
    )
    def test_missing_or_invalid_required_field_rejected(self, kind, payload, bad_field):
        serializer = CreateBetEventSerializer(data={"kind": kind, "payload": payload})
        assert not serializer.is_valid()
        assert bad_field in serializer.errors["payload"]

    @parameterized.expand(
        [
            ("node.spawned", {"node_id": "root.0", "parent_node_id": "root", "depth": 1}),
            ("node.finished", {"node_id": "root.0", "cost": 1.5}),
            ("node.failed", {"node_id": "root.0", "summary": "sandbox timed out"}),
            ("budget.exceeded", {"node_id": "root.0", "cap": "max_depth"}),
            ("knowledge.published", {"repo": "file:///memory", "title": "an insight"}),
        ]
    )
    def test_well_formed_payload_accepted(self, kind, payload):
        serializer = CreateBetEventSerializer(data={"kind": kind, "payload": payload})
        assert serializer.is_valid(), serializer.errors

    def test_existing_kind_payload_is_untouched_free_json(self):
        """gate.result predates the new per-kind validation and stays a free-form payload."""
        serializer = CreateBetEventSerializer(data={"kind": "gate.result", "payload": {"anything": "goes"}})
        assert serializer.is_valid(), serializer.errors


class TestRunConfigBuildLoopValidation(SimpleTestCase):
    """A plain managed bet's run_config (no build_loop) must keep validating exactly as
    before ADR-5 — the acceptance criterion that build_loop is fully optional."""

    @parameterized.expand(
        [
            ({},),
            ({"command": "echo hello"},),
            ({"command": "echo hello", "env": {"FOO": "bar"}, "caps": {"max_depth": 2}},),
        ]
    )
    def test_plain_run_config_without_build_loop_still_validates(self, run_config):
        serializer = RunConfigSerializer(data=run_config)
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data.get("build_loop") is None

    @parameterized.expand(
        [
            ({"builder": {"command": "run-builder"}}, "target_repo"),
            ({"target_repo": {"base_ref": "main"}, "builder": {"command": "run-builder"}}, "target_repo"),
            ({"target_repo": {"url": "https://x/y.git", "base_ref": "main"}}, "builder"),
        ]
    )
    def test_build_loop_missing_required_field_rejected(self, build_loop, missing_field):
        serializer = RunConfigSerializer(data={"build_loop": build_loop})
        assert not serializer.is_valid()
        assert missing_field in serializer.errors["build_loop"]

    def test_well_formed_build_loop_round_trips(self):
        build_loop = {
            "target_repo": {"url": "https://x:tok@gitea/o/r.git", "base_ref": "main"},
            "test_writer": {"command": "claude -p test-writer-prompt --dangerously-skip-permissions"},
            "builder": {"command": "claude -p builder-prompt --dangerously-skip-permissions", "env": {"FOO": "bar"}},
            "max_gate_iterations": 5,
        }
        serializer = RunConfigSerializer(data={"build_loop": build_loop})
        assert serializer.is_valid(), serializer.errors
        validated = serializer.validated_data["build_loop"]
        assert validated["max_gate_iterations"] == 5
        assert validated["builder"]["env"] == {"FOO": "bar"}
        assert validated["target_repo"]["base_ref"] == "main"

    def test_build_loop_without_test_writer_is_valid(self):
        """test_writer is optional — skipping it must not be rejected (criterion 2)."""
        build_loop = {
            "target_repo": {"url": "https://x/y.git", "base_ref": "main"},
            "builder": {"command": "run-builder"},
        }
        serializer = RunConfigSerializer(data={"build_loop": build_loop})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["build_loop"]["test_writer"] is None
