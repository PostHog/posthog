"""Personal ReviewHog preferences: one typed schema over sparse JSON.

A person's stored preferences hold only the keys they changed. An absent key means the inherited
value: the project default for the keys a project can set, else the code default. Reads drop
unknown keys and invalid values, so a removed or renamed key never breaks a load. Writes validate
every key and drop a value that equals the inherited one, so a later change of the project default
reaches everyone who did not choose their own value.

This module is pure. `ReviewUserSettings` and `ReviewProjectSettings` store the dicts.
"""

from collections.abc import Mapping
from typing import cast

from django.db import models

from posthog.dataclasses import frozen

PreferenceValue = str | bool


class DefaultReviewMode(models.TextChoices):
    FOLLOW = "follow", "Follow each repository"
    FLASH = "flash", "Flash everywhere"
    OFF = "off", "Off everywhere"


class UrgencyThreshold(models.TextChoices):
    # Values mirror `IssuePriority`, so the threshold compares directly against finding priorities.
    CONSIDER = "consider", "Consider (all)"
    SHOULD_FIX = "should_fix", "Should fix"
    MUST_FIX = "must_fix", "Must fix"


class PreferenceSource(models.TextChoices):
    USER = "user", "Set by the user"
    PROJECT = "project", "Project default"
    DEFAULT = "default", "Built-in default"


class InvalidPreference(ValueError):
    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key


@frozen
class PreferenceField:
    key: str
    default: PreferenceValue
    # None for a boolean preference.
    choices: tuple[str, ...] | None = None
    project_default: bool = False

    def is_valid(self, value: object) -> bool:
        if self.choices is None:
            return isinstance(value, bool)
        return isinstance(value, str) and value in self.choices


PREFERENCE_FIELDS: tuple[PreferenceField, ...] = (
    PreferenceField(
        key="default_review_mode", default=DefaultReviewMode.FOLLOW.value, choices=tuple(DefaultReviewMode.values)
    ),
    PreferenceField(key="resolve_comments", default=False),
    PreferenceField(
        key="urgency_threshold",
        default=UrgencyThreshold.CONSIDER.value,
        choices=tuple(UrgencyThreshold.values),
        project_default=True,
    ),
    PreferenceField(key="celebrate_clean_reviews", default=True, project_default=True),
    PreferenceField(key="review_inbox_prs", default=False),
    PreferenceField(key="stamphog_review_inbox_prs", default=False),
)
PREFERENCE_KEYS: tuple[str, ...] = tuple(field.key for field in PREFERENCE_FIELDS)
PROJECT_DEFAULT_FIELDS: tuple[PreferenceField, ...] = tuple(
    field for field in PREFERENCE_FIELDS if field.project_default
)
PROJECT_DEFAULT_KEYS: tuple[str, ...] = tuple(field.key for field in PROJECT_DEFAULT_FIELDS)


def clean_values(raw: object, fields: tuple[PreferenceField, ...]) -> dict[str, PreferenceValue]:
    """The valid known keys of a stored dict. Anything else is ignored."""
    if not isinstance(raw, Mapping):
        return {}
    return {field.key: raw[field.key] for field in fields if field.key in raw and field.is_valid(raw[field.key])}


def _validated_changes(
    changes: Mapping[str, object], fields: tuple[PreferenceField, ...]
) -> dict[str, PreferenceValue]:
    by_key = {field.key: field for field in fields}
    validated: dict[str, PreferenceValue] = {}
    for key, value in changes.items():
        field = by_key.get(key)
        if field is None:
            raise InvalidPreference(key, f"Unknown preference '{key}'.")
        if not field.is_valid(value):
            expected = "true or false" if field.choices is None else ", ".join(field.choices)
            raise InvalidPreference(key, f"Invalid value for '{key}'. Expected one of: {expected}.")
        validated[key] = cast(PreferenceValue, value)
    return validated


@frozen
class ReviewProjectDefaults:
    """A project's defaults for the Full review preferences, with the code default filled in."""

    urgency_threshold: UrgencyThreshold
    celebrate_clean_reviews: bool
    stored: Mapping[str, PreferenceValue]

    @classmethod
    def resolve(cls, stored: object) -> "ReviewProjectDefaults":
        values = clean_values(stored, PROJECT_DEFAULT_FIELDS)
        effective = {field.key: values.get(field.key, field.default) for field in PROJECT_DEFAULT_FIELDS}
        return cls(
            urgency_threshold=UrgencyThreshold(str(effective["urgency_threshold"])),
            celebrate_clean_reviews=bool(effective["celebrate_clean_reviews"]),
            stored=values,
        )

    def with_changes(self, changes: Mapping[str, object]) -> dict[str, PreferenceValue]:
        """The stored dict after `changes`. A value equal to the code default is removed.

        Raises `InvalidPreference` for an unknown key or an invalid value.
        """
        merged = {**self.stored, **_validated_changes(changes, PROJECT_DEFAULT_FIELDS)}
        return {
            field.key: merged[field.key]
            for field in PROJECT_DEFAULT_FIELDS
            if merged.get(field.key, field.default) != field.default
        }


@frozen
class ReviewPreferences:
    """A person's effective preferences, and where each value comes from."""

    default_review_mode: DefaultReviewMode
    resolve_comments: bool
    urgency_threshold: UrgencyThreshold
    celebrate_clean_reviews: bool
    review_inbox_prs: bool
    stamphog_review_inbox_prs: bool
    sources: Mapping[str, PreferenceSource]
    stored: Mapping[str, PreferenceValue]
    project: ReviewProjectDefaults

    @staticmethod
    def _inherited(field: PreferenceField, project: ReviewProjectDefaults) -> tuple[PreferenceValue, PreferenceSource]:
        if field.project_default and field.key in project.stored:
            return project.stored[field.key], PreferenceSource.PROJECT
        return field.default, PreferenceSource.DEFAULT

    @classmethod
    def resolve(cls, stored: object, project: ReviewProjectDefaults) -> "ReviewPreferences":
        values = clean_values(stored, PREFERENCE_FIELDS)
        effective: dict[str, PreferenceValue] = {}
        sources: dict[str, PreferenceSource] = {}
        for field in PREFERENCE_FIELDS:
            if field.key in values:
                effective[field.key], sources[field.key] = values[field.key], PreferenceSource.USER
            else:
                effective[field.key], sources[field.key] = cls._inherited(field, project)
        return cls(
            default_review_mode=DefaultReviewMode(str(effective["default_review_mode"])),
            resolve_comments=bool(effective["resolve_comments"]),
            urgency_threshold=UrgencyThreshold(str(effective["urgency_threshold"])),
            celebrate_clean_reviews=bool(effective["celebrate_clean_reviews"]),
            review_inbox_prs=bool(effective["review_inbox_prs"]),
            stamphog_review_inbox_prs=bool(effective["stamphog_review_inbox_prs"]),
            sources=sources,
            stored=values,
            project=project,
        )

    @classmethod
    def defaults(cls) -> "ReviewPreferences":
        return cls.resolve({}, ReviewProjectDefaults.resolve({}))

    def with_changes(self, changes: Mapping[str, object]) -> dict[str, PreferenceValue]:
        """The stored dict after `changes`. A value equal to the inherited value is removed.

        Raises `InvalidPreference` for an unknown key or an invalid value.
        """
        merged = {**self.stored, **_validated_changes(changes, PREFERENCE_FIELDS)}
        stored: dict[str, PreferenceValue] = {}
        for field in PREFERENCE_FIELDS:
            inherited, _source = self._inherited(field, self.project)
            if field.key in merged and merged[field.key] != inherited:
                stored[field.key] = merged[field.key]
        return stored
