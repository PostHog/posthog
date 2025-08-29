from typing import Any, Optional

from django.db import connections, models, transaction

from posthog.models.utils import UUIDT

# Check for read replica
if "persons_db_reader" in connections:
    READ_DB_FOR_PERSONS = "persons_db_reader"
elif "replica" in connections:
    READ_DB_FOR_PERSONS = "replica"
else:
    READ_DB_FOR_PERSONS = "default"

MAX_LIMIT_DISTINCT_IDS = 2500


class PersonManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        with transaction.atomic(using=self.db):
            if not kwargs.get("distinct_ids"):
                return super().create(*args, **kwargs)
            distinct_ids = kwargs.pop("distinct_ids")
            person = super().create(*args, **kwargs)
            person._add_distinct_ids(distinct_ids)
            return person


class Person(models.Model):
    """
    Person model that lives in the persons database.
    Uses team_id as IntegerField instead of ForeignKey to avoid cross-database constraints.
    """

    id = models.BigAutoField(primary_key=True)
    _distinct_ids: Optional[list[str]]

    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    # used to prevent race conditions with set and set_once
    properties_last_updated_at = models.JSONField(default=dict, null=True, blank=True)

    # used for evaluating if we need to override the value or not (value: set or set_once)
    properties_last_operation = models.JSONField(null=True, blank=True)

    # Changed from ForeignKey to IntegerField
    team_id = models.IntegerField(db_index=True)

    properties = models.JSONField(default=dict)
    is_user = models.IntegerField(null=True, blank=True, db_column="is_user_id")
    is_identified = models.BooleanField(default=False)
    uuid = models.UUIDField(db_index=True, default=UUIDT, editable=False)

    # current version of the person, used to sync with ClickHouse and collapse rows correctly
    version = models.BigIntegerField(null=True, blank=True)

    objects = PersonManager()

    class Meta:
        db_table = "posthog_person"
        # Keeping indexes from original model
        indexes = [
            models.Index(fields=["team_id", "-id"]),
        ]

    @property
    def team(self):
        """Lazy-load team when needed for compatibility"""
        from posthog.models import Team

        return Team.objects.get(id=self.team_id)

    @property
    def distinct_ids(self) -> list[str]:
        if hasattr(self, "distinct_ids_cache"):
            return [id.distinct_id for id in self.distinct_ids_cache]
        if hasattr(self, "_distinct_ids") and self._distinct_ids:
            return self._distinct_ids
        return [
            id[0]
            for id in PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(person=self, team_id=self.team_id)
            .order_by("id")
            .values_list("distinct_id")
        ]

    @property
    def email(self) -> Optional[str]:
        return self.properties.get("email")

    def add_distinct_id(self, distinct_id: str) -> None:
        PersonDistinctId.objects.create(person=self, distinct_id=distinct_id, team_id=self.team_id)

    def _add_distinct_ids(self, distinct_ids: list[str]) -> None:
        for distinct_id in distinct_ids:
            self.add_distinct_id(distinct_id)

    def split_person(self, main_distinct_id: Optional[str], max_splits: Optional[int] = None):
        # Import here to avoid circular imports
        from posthog.models.person.missing_person import uuidFromDistinctId

        original_person = Person.objects.get(pk=self.pk)
        distinct_ids = original_person.distinct_ids
        original_person_version = original_person.version or 0
        if not main_distinct_id:
            self.properties = {}
            self.save()
            main_distinct_id = distinct_ids[0]

        if max_splits is not None and len(distinct_ids) > max_splits:
            # Split the last N distinct_ids of the list
            distinct_ids = distinct_ids[-1 * max_splits :]

        for distinct_id in distinct_ids:
            if not distinct_id == main_distinct_id:
                with transaction.atomic():
                    pdi = PersonDistinctId.objects.select_for_update().get(person=self, distinct_id=distinct_id)
                    person, _ = Person.objects.get_or_create(
                        uuid=uuidFromDistinctId(self.team_id, distinct_id),
                        team_id=self.team_id,
                        defaults={
                            "version": original_person_version + 1,
                        },
                    )
                    pdi.person_id = str(person.id)
                    pdi.version = (pdi.version or 0) + 1
                    pdi.save(update_fields=["version", "person_id"])


class PersonDistinctId(models.Model):
    """
    Links distinct IDs to Person records.
    """

    id = models.BigAutoField(primary_key=True)
    # Changed from ForeignKey to IntegerField
    team_id = models.IntegerField(db_index=False)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    distinct_id = models.CharField(max_length=400)
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "posthog_persondistinctid"
        constraints = [
            models.UniqueConstraint(fields=["team_id", "distinct_id"], name="personsdb_unique_distinct_id_for_team")
        ]

    @property
    def team(self):
        """Lazy-load team when needed for compatibility"""
        from posthog.models import Team

        return Team.objects.get(id=self.team_id)


class PersonlessDistinctId(models.Model):
    """
    Distinct IDs that don't yet have an associated Person.
    Used in the merge queue process.
    """

    id = models.BigAutoField(primary_key=True)
    # Changed from ForeignKey to IntegerField
    team_id = models.IntegerField(db_index=False)
    distinct_id = models.CharField(max_length=400)
    is_merged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    class Meta:
        db_table = "posthog_personlessdistinctid"
        constraints = [
            models.UniqueConstraint(fields=["team_id", "distinct_id"], name="personsdb_unique_personless_distinct_id")
        ]

    @property
    def team(self):
        """Lazy-load team when needed for compatibility"""
        from posthog.models import Team

        return Team.objects.get(id=self.team_id)


class PersonOverrideMapping(models.Model):
    """
    Mapping for person overrides.
    Note: Marked as NOT USED in original code.
    """

    id = models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    uuid = models.UUIDField()

    class Meta:
        db_table = "posthog_personoverridemapping"
        constraints = [
            models.UniqueConstraint(fields=["team_id", "uuid"], name="personsdb_unique_uuid"),
        ]


class PersonOverride(models.Model):
    """
    Person override records.
    Note: Marked as NOT USED in original code.
    """

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    # Changed from ForeignKey to IntegerField
    team_id = models.IntegerField()

    old_person_id = models.ForeignKey(
        "PersonOverrideMapping",
        db_column="old_person_id",
        related_name="person_override_old",
        on_delete=models.CASCADE,
    )
    override_person_id = models.ForeignKey(
        "PersonOverrideMapping",
        db_column="override_person_id",
        related_name="person_override_override",
        on_delete=models.CASCADE,
    )
    oldest_event = models.DateTimeField()
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "posthog_personoverride"
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "old_person_id"],
                name="personsdb_unique_override_per_old_person_id",
            ),
        ]

    @property
    def team(self):
        """Lazy-load team when needed for compatibility"""
        from posthog.models import Team

        return Team.objects.get(id=self.team_id)


class PendingPersonOverride(models.Model):
    """
    Pending person overrides.
    Note: Marked as NOT USED in original code.
    """

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    old_person_id = models.UUIDField()
    override_person_id = models.UUIDField()
    oldest_event = models.DateTimeField()

    class Meta:
        db_table = "posthog_pendingpersonoverride"


class FlatPersonOverride(models.Model):
    """
    Flat person override records.
    Note: Marked as NOT USED in original code.
    """

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team_id = models.BigIntegerField()
    old_person_id = models.UUIDField()
    override_person_id = models.UUIDField()
    oldest_event = models.DateTimeField()
    version = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "posthog_flatpersonoverride"
        indexes = [
            models.Index(fields=["team_id", "override_person_id"], name="personsdb_fla_team_override"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "old_person_id"],
                name="unique_flat_override",
            ),
        ]


class FeatureFlagHashKeyOverride(models.Model):
    """
    Override hash keys for feature flags.
    """

    # Can't use a foreign key to feature_flag_key directly, since
    # the unique constraint is on (team_id+key), and not just key.
    feature_flag_key = models.CharField(max_length=400)
    person = models.ForeignKey("Person", on_delete=models.CASCADE)
    # Changed from ForeignKey to IntegerField
    team_id = models.IntegerField()
    hash_key = models.CharField(max_length=400)

    class Meta:
        db_table = "posthog_featureflaghashkeyoverride"
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "person", "feature_flag_key"],
                name="personsdb_unique_hash_key_combo",
            )
        ]

    @property
    def team(self):
        """Lazy-load team when needed for compatibility"""
        from posthog.models import Team

        return Team.objects.get(id=self.team_id)


class CohortPeople(models.Model):
    """
    Mapping of people to cohorts.
    """

    id = models.BigAutoField(primary_key=True)
    # Changed from ForeignKey to IntegerField
    cohort_id = models.IntegerField()
    person = models.ForeignKey("Person", on_delete=models.CASCADE)
    version = models.IntegerField(blank=True, null=True)

    class Meta:
        db_table = "posthog_cohortpeople"
        indexes = [models.Index(fields=["cohort_id", "person_id"], name="personsdb_cohort_person_idx")]

    @property
    def cohort(self):
        """Lazy-load cohort when needed for compatibility"""
        from posthog.models import Cohort

        return Cohort.objects.get(id=self.cohort_id)


class Group(models.Model):
    """
    Group model that lives in the persons database.
    """

    # Changed from ForeignKey to IntegerField
    team_id = models.IntegerField()
    group_key = models.CharField(max_length=400, null=False, blank=False)
    group_type_index = models.IntegerField(null=False, blank=False)

    group_properties = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    # used to prevent race conditions with set and set_once
    properties_last_updated_at = models.JSONField(default=dict)

    # used for evaluating if we need to override the value or not (value: set or set_once)
    properties_last_operation = models.JSONField(default=dict)

    # current version of the group, used to sync with ClickHouse and collapse rows correctly
    version = models.BigIntegerField(null=False)

    class Meta:
        db_table = "posthog_group"
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "group_key", "group_type_index"],
                name="personsdb_unique_team_group_type_combo",
            )
        ]

    @property
    def team(self):
        """Lazy-load team when needed for compatibility"""
        from posthog.models import Team

        return Team.objects.get(id=self.team_id)
