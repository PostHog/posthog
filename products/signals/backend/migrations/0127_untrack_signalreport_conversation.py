from django.db import migrations

from posthog.migration_helpers import DropForeignKey, untrack_field


class Migration(migrations.Migration):
    """Take `conversation` out of Django's state and drop its constraint.

    deprecate_field() had hidden the column from the ORM, so Django stopped setting it to
    NULL when a conversation was deleted while the foreign key stayed. The constraint is
    DEFERRABLE INITIALLY DEFERRED, so the delete finished and then failed at COMMIT.

    The column stays. Only Django's state and the constraint change here.
    """

    dependencies = [
        ("signals", "0126_signalteamconfig_issue_tracking_config_and_more"),
    ]

    operations = [
        untrack_field(
            "signalreport",
            "conversation",
            database_operations=[
                DropForeignKey("signals_signalreport", column="conversation_id"),
            ],
        ),
    ]
