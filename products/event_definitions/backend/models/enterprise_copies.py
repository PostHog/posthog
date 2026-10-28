"""The enterprise definition fields, and the base-table fields that hold a copy of each.

The enterprise fields move from `ee_enterpriseeventdefinition` and `ee_enterprisepropertydefinition`
onto `posthog_eventdefinition` and `posthog_propertydefinition`. Until reads move over, the enterprise
models write each value to both tables, and nothing reads the copies. Django does not let a field on
the base model share a name with a field on the enterprise subclass, so the copies carry a `base_`
prefix. Their columns already have the final names.
"""

from collections.abc import Iterable, Mapping

from django.db import models

EVENT_DEFINITION_COPIES: Mapping[str, str] = {
    "description": "base_description",
    "owner": "base_owner",
    "updated_at": "base_updated_at",
    "updated_by": "base_updated_by",
    "verified": "base_verified",
    "verified_at": "base_verified_at",
    "verified_by": "base_verified_by",
    "hidden": "base_hidden",
    "default_columns": "base_default_columns",
}

PROPERTY_DEFINITION_COPIES: Mapping[str, str] = {
    "description": "base_description",
    "updated_at": "base_updated_at",
    "updated_by": "base_updated_by",
    "verified": "base_verified",
    "verified_at": "base_verified_at",
    "verified_by": "base_verified_by",
    "hidden": "base_hidden",
}


def copy_enterprise_fields(
    instance: models.Model, copies: Mapping[str, str], update_fields: Iterable[str] | None
) -> set[str] | None:
    """Copy the enterprise values onto their base-table fields, and return the `update_fields` to save.

    A partial save that names an enterprise field must also name its copy, or the copy goes stale.
    """
    opts = instance._meta
    for source_name, target_name in copies.items():
        source = opts.get_field(source_name)
        target = opts.get_field(target_name)
        setattr(instance, target.attname, getattr(instance, source.attname))

    if update_fields is None:
        return None
    requested = set(update_fields)
    return requested | {
        copies[name] for name in copies if name in requested or opts.get_field(name).attname in requested
    }
