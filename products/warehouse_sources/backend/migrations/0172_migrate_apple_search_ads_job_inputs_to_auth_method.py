from typing import Any, Optional

from django.db import migrations

# The key pair fields, which are copied from the top level into the `auth_method` branch when the
# source gained the Sign in with Apple option. They remain flat for old workers during rollout.
# Everything else on an Apple Ads source
# (`ad_account_id`, `org_id`, `start_date`) stays at the top level and must not move.
KEY_PAIR_FIELDS = ("client_id", "apple_team_id", "key_id", "private_key")


def nest_key_pair_under_auth_method(job_inputs: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The migrated `job_inputs`, or None when the source already carries a branch.

    Every Apple Ads source that exists today authenticates with its own key pair, because that
    was the only option. Naming the branch explicitly keeps the edit form on it: the branch
    defaults to the sign-in option, so a source left flat renders with its key fields hidden.
    Keeping the flat fields lets workers from the previous release continue syncing during rollout.
    """
    if "auth_method" in job_inputs:
        return None

    migrated = dict(job_inputs)
    auth_method: dict[str, Any] = {"selection": "key_pair"}
    for field in KEY_PAIR_FIELDS:
        auth_method[field] = migrated.get(field, "")
    migrated["auth_method"] = auth_method
    return migrated


def flatten_auth_method_to_key_pair(job_inputs: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The pre-branch `job_inputs`, or None when there is nothing the previous release can read.

    A source connected through Sign in with Apple has no flat shape to go back to, because its
    credential is an integration id the previous release has no field for. Leaving it alone makes
    it report a config error on a rollback, which is honest: that release cannot sync it either.
    """
    auth_method = job_inputs.get("auth_method")
    if not isinstance(auth_method, dict) or auth_method.get("selection") != "key_pair":
        return None

    flattened = dict(job_inputs)
    flattened.pop("auth_method", None)
    for field in KEY_PAIR_FIELDS:
        flattened[field] = auth_method.get(field, "")
    return flattened


def _rewrite_job_inputs(apps, rewrite) -> None:
    ExternalDataSource = apps.get_model("warehouse_sources", "ExternalDataSource")

    for source in ExternalDataSource.objects.filter(source_type="AppleSearchAds"):
        if not isinstance(source.job_inputs, dict):
            continue

        rewritten = rewrite(source.job_inputs)
        if rewritten is None:
            continue

        ExternalDataSource.objects.filter(pk=source.pk, job_inputs=source.job_inputs).update(job_inputs=rewritten)


def migrate_apple_search_ads_job_inputs(apps, schema_editor):
    _rewrite_job_inputs(apps, nest_key_pair_under_auth_method)


def reverse_migrate_apple_search_ads_job_inputs(apps, schema_editor):
    _rewrite_job_inputs(apps, flatten_auth_method_to_key_pair)


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0171_externaldatajob_pipeline_created_idx"),
    ]

    operations = [
        migrations.RunPython(migrate_apple_search_ads_job_inputs, reverse_migrate_apple_search_ads_job_inputs),
    ]
