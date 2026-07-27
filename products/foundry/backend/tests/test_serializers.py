from django.test import SimpleTestCase

from parameterized import parameterized

from products.foundry.backend.presentation.serializers import CreateBetEventSerializer


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
