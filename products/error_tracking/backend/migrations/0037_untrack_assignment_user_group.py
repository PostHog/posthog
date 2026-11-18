from django.db import migrations

from posthog.migration_helpers import DropForeignKey, untrack_field


class Migration(migrations.Migration):
    """Take the `user_group` fields out of Django's state and drop their constraints.

    deprecate_field() had hidden these three columns from the ORM, so Django stopped
    cascading into them while their foreign keys to posthog_usergroup stayed. Those
    constraints are DEFERRABLE INITIALLY DEFERRED, so deleting a user group finished its
    cascade and then failed at COMMIT. Team deletion reaches the same failure, because a
    team delete cascades into its user groups.

    The columns stay. Only Django's state and the constraints change here.
    """

    dependencies = [
        ("error_tracking", "0036_add_stackframe_js_frames_index"),
    ]

    operations = [
        untrack_field(
            "errortrackingissueassignment",
            "user_group",
            database_operations=[
                DropForeignKey("posthog_errortrackingissueassignment", column="user_group_id"),
            ],
        ),
        untrack_field(
            "errortrackinggroupingrule",
            "user_group",
            database_operations=[
                DropForeignKey("posthog_errortrackinggroupingrule", column="user_group_id"),
            ],
        ),
        untrack_field(
            "errortrackingassignmentrule",
            "user_group",
            database_operations=[
                DropForeignKey("posthog_errortrackingassignmentrule", column="user_group_id"),
            ],
        ),
    ]
