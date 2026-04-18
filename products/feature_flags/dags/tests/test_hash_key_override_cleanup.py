import pytest

from dagster import build_asset_context

from posthog.models import Organization, Team
from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagHashKeyOverride
from posthog.models.person import Person

from products.feature_flags.dags.hash_key_override_cleanup import (
    HashKeyOverrideCleanupConfig,
    hash_key_override_cleanup,
)

TEST_DATABASES = ["default", "persons_db_writer"]


def _make_team(name: str = "Test") -> Team:
    org = Organization.objects.create(name=f"{name} Org")
    return Team.objects.create(organization=org, name=name)


def _make_override(
    team: Team, person: Person, feature_flag_key: str, hash_key: str = "h"
) -> FeatureFlagHashKeyOverride:
    return FeatureFlagHashKeyOverride.objects.create(
        team_id=team.pk,
        person_id=person.id,
        feature_flag_key=feature_flag_key,
        hash_key=hash_key,
    )


def _run_cleanup(config: HashKeyOverrideCleanupConfig | None = None):
    cfg = config or HashKeyOverrideCleanupConfig()
    context = build_asset_context()
    return hash_key_override_cleanup(context, cfg)


@pytest.mark.django_db(databases=TEST_DATABASES)
@pytest.mark.parametrize(
    "scenario,flags,override_keys,expected_remaining",
    [
        (
            "soft_delete_without_rename",
            [("live_flag", False), ("stale_flag", True)],
            ["live_flag", "stale_flag"],
            {"live_flag"},
        ),
        (
            "soft_delete_with_rename",
            [("original:deleted:42", True)],
            ["original"],
            set(),
        ),
        (
            "hard_delete_orphan",
            [("current", False)],
            ["current", "was_hard_deleted"],
            {"current"},
        ),
    ],
)
def test_deletes_stale_overrides_across_deletion_paths(scenario, flags, override_keys, expected_remaining):
    team = _make_team()
    person = Person.objects.create(team=team, distinct_ids=["u1"])
    for key, is_deleted in flags:
        FeatureFlag.objects.create(team=team, key=key, deleted=is_deleted)
    for key in override_keys:
        _make_override(team, person, key)

    result = _run_cleanup()

    remaining = set(
        FeatureFlagHashKeyOverride.objects.filter(team_id=team.pk).values_list("feature_flag_key", flat=True)
    )
    assert remaining == expected_remaining
    assert result.metadata["rows_deleted"].value == len(override_keys) - len(expected_remaining)


@pytest.mark.django_db(databases=TEST_DATABASES)
def test_preserves_overrides_for_live_flags():
    team = _make_team()
    person = Person.objects.create(team=team, distinct_ids=["u1"])
    for key in ["a", "b", "c"]:
        FeatureFlag.objects.create(team=team, key=key)
        _make_override(team, person, key)

    result = _run_cleanup()

    assert FeatureFlagHashKeyOverride.objects.filter(team_id=team.pk).count() == 3
    assert result.metadata["rows_deleted"].value == 0


@pytest.mark.django_db(databases=TEST_DATABASES)
def test_dry_run_counts_without_deleting():
    team = _make_team()
    person = Person.objects.create(team=team, distinct_ids=["u1"])
    FeatureFlag.objects.create(team=team, key="live")
    FeatureFlag.objects.create(team=team, key="gone", deleted=True)
    _make_override(team, person, "live")
    _make_override(team, person, "gone")

    result = _run_cleanup(HashKeyOverrideCleanupConfig(dry_run=True))

    assert FeatureFlagHashKeyOverride.objects.filter(team_id=team.pk).count() == 2
    assert result.metadata["rows_deleted"].value == 1
    assert result.metadata["dry_run"].value is True


@pytest.mark.django_db(databases=TEST_DATABASES)
def test_team_isolation():
    team_a = _make_team("A")
    team_b = _make_team("B")
    person_a = Person.objects.create(team=team_a, distinct_ids=["a1"])
    person_b = Person.objects.create(team=team_b, distinct_ids=["b1"])

    FeatureFlag.objects.create(team=team_a, key="shared_key")
    FeatureFlag.objects.create(team=team_b, key="shared_key", deleted=True)

    _make_override(team_a, person_a, "shared_key")
    _make_override(team_b, person_b, "shared_key")

    _run_cleanup()

    assert FeatureFlagHashKeyOverride.objects.filter(team_id=team_a.pk).count() == 1
    assert FeatureFlagHashKeyOverride.objects.filter(team_id=team_b.pk).count() == 0


@pytest.mark.django_db(databases=TEST_DATABASES)
def test_empty_state_is_noop():
    result = _run_cleanup()

    assert result.metadata["rows_deleted"].value == 0
    assert result.metadata["teams_processed"].value == 0
    assert result.metadata["teams_failed"].value == 0


@pytest.mark.django_db(databases=TEST_DATABASES)
def test_batches_deletes_when_stale_keys_exceed_batch_size():
    team = _make_team()
    person = Person.objects.create(team=team, distinct_ids=["u1"])
    for i in range(5):
        FeatureFlag.objects.create(team=team, key=f"gone_{i}", deleted=True)
        _make_override(team, person, f"gone_{i}")

    result = _run_cleanup(HashKeyOverrideCleanupConfig(batch_size=2))

    assert not FeatureFlagHashKeyOverride.objects.filter(team_id=team.pk).exists()
    assert result.metadata["rows_deleted"].value == 5
    assert result.metadata["stale_keys_found"].value == 5


@pytest.mark.django_db(databases=TEST_DATABASES)
def test_row_batching_when_single_stale_key_has_many_rows():
    # One stale key with many override rows (many persons) must be deleted across multiple
    # DELETE statements so a runaway key doesn't trigger a single massive transaction.
    team = _make_team()
    for i in range(5):
        person = Person.objects.create(team=team, distinct_ids=[f"u{i}"])
        _make_override(team, person, "stale")

    result = _run_cleanup(HashKeyOverrideCleanupConfig(batch_size=2))

    assert not FeatureFlagHashKeyOverride.objects.filter(team_id=team.pk).exists()
    assert result.metadata["rows_deleted"].value == 5
    assert result.metadata["stale_keys_found"].value == 1


@pytest.mark.django_db(databases=TEST_DATABASES)
def test_cleans_team_with_no_flags_remaining():
    # A team whose flags were all hard-deleted still has overrides left behind.
    # Sourcing team_ids from the overrides table ensures they get cleaned.
    team = _make_team()
    person = Person.objects.create(team=team, distinct_ids=["u1"])
    _make_override(team, person, "ghost")

    assert not FeatureFlag.objects_including_soft_deleted.filter(team_id=team.pk).exists()

    result = _run_cleanup()

    assert not FeatureFlagHashKeyOverride.objects.filter(team_id=team.pk).exists()
    assert result.metadata["rows_deleted"].value == 1
    assert result.metadata["teams_processed"].value == 1
