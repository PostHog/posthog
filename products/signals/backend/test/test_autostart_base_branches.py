import pytest

from products.signals.backend.serializers import SignalTeamConfigSerializer


@pytest.mark.parametrize(
    ("input_branches", "expected"),
    [
        # Whitespace trimmed, repo key lowercased, and the blank-branch entry
        # dropped (the UI removes an override by clearing its branch).
        ({"Acme/Web": "  staging  ", "acme/api": ""}, {"acme/web": "staging"}),
        ({}, {}),
    ],
)
def test_serializer_normalizes_valid_branches(input_branches, expected):
    serializer = SignalTeamConfigSerializer(data={"autostart_base_branches": input_branches}, partial=True)
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["autostart_base_branches"] == expected


@pytest.mark.parametrize("bad_repo", ["acme", "acme/web/extra", "/web", "acme/", ""])
def test_serializer_rejects_malformed_repo_keys(bad_repo):
    serializer = SignalTeamConfigSerializer(data={"autostart_base_branches": {bad_repo: "staging"}}, partial=True)
    assert not serializer.is_valid()
    assert "autostart_base_branches" in serializer.errors
