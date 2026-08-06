import pytest

from products.signals.backend.auto_start import _AutostartPrSettings, _resolve_autostart_pr_settings
from products.signals.backend.models import SignalTeamConfig
from products.signals.backend.serializers import SignalTeamConfigSerializer


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        # Repo keys lowercased; bool coerced.
        ("autostart_pr_draft", {"Acme/Web": False, "acme/api": True}, {"acme/web": False, "acme/api": True}),
        # Labels trimmed, blanks dropped, deduped while preserving order; blank repo list drops the repo.
        (
            "autostart_pr_labels",
            {"Acme/Web": ["  bot-review ", "bot-review", "", "  "], "acme/api": []},
            {"acme/web": ["bot-review"]},
        ),
        # Instructions trimmed; a whitespace-only value drops the repo entirely.
        (
            "autostart_pr_instructions",
            {"Acme/Web": "  Reviewers: @team  ", "acme/api": "   "},
            {"acme/web": "Reviewers: @team"},
        ),
    ],
)
def test_serializer_normalizes_valid_pr_settings(field, value, expected):
    serializer = SignalTeamConfigSerializer(data={field: value}, partial=True)
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data[field] == expected


@pytest.mark.parametrize("field", ["autostart_pr_draft", "autostart_pr_labels", "autostart_pr_instructions"])
@pytest.mark.parametrize("bad_repo", ["acme", "acme/web/extra", "/web", "acme/", ""])
def test_serializer_rejects_malformed_repo_keys(field, bad_repo):
    sample = {
        "autostart_pr_draft": True,
        "autostart_pr_labels": ["bot-review"],
        "autostart_pr_instructions": "hello",
    }[field]
    serializer = SignalTeamConfigSerializer(data={field: {bad_repo: sample}}, partial=True)
    assert not serializer.is_valid()
    assert field in serializer.errors


def test_resolve_pr_settings_defaults_without_config():
    # No config row (or no repo) must reproduce today's behavior: draft, default branch, no labels/instructions.
    assert _resolve_autostart_pr_settings(None, "acme/web") == _AutostartPrSettings()
    assert _resolve_autostart_pr_settings(SignalTeamConfig(), "") == _AutostartPrSettings()


def test_resolve_pr_settings_reads_per_repo_config():
    config = SignalTeamConfig(
        autostart_base_branches={"acme/web": "staging"},
        autostart_pr_draft={"acme/web": False},
        autostart_pr_labels={"acme/web": ["bot-review", "self-driving"]},
        autostart_pr_instructions={"acme/web": "Open ready and label it."},
    )
    # Lookup is case-insensitive on the repo.
    settings = _resolve_autostart_pr_settings(config, "Acme/Web")
    assert settings == _AutostartPrSettings(
        base_branch="staging",
        draft=False,
        labels=["bot-review", "self-driving"],
        instructions="Open ready and label it.",
    )


def test_resolve_pr_settings_repo_absent_from_maps_keeps_draft_default():
    # A repo configured for one setting but absent from the draft map still defaults to draft.
    config = SignalTeamConfig(autostart_pr_labels={"acme/web": ["bot-review"]})
    settings = _resolve_autostart_pr_settings(config, "acme/web")
    assert settings.draft is True
    assert settings.labels == ["bot-review"]
    assert settings.base_branch is None
    assert settings.instructions is None
