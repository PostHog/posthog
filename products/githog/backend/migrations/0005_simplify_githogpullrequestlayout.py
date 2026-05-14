import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Make GitHogPullRequestLayout a per-user singleton.

    The layout used to be keyed by (team, user, repository, pr_number); now it's
    a single row per user that applies to every PR across every repo and team.
    """

    dependencies = [
        ("githog", "0004_githogpullrequestmessage"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="githogpullrequestlayout",
            name="unique_githog_pr_layout_per_user",
        ),
        migrations.RemoveIndex(
            model_name="githogpullrequestlayout",
            name="githog_gith_team_id_4aec24_idx",
        ),
        # Drop all existing rows: the new schema is a singleton per user, and the
        # old per-PR layouts can't be meaningfully collapsed into a single row.
        migrations.RunSQL(
            sql='DELETE FROM "githog_githogpullrequestlayout";',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveField(
            model_name="githogpullrequestlayout",
            name="team",
        ),
        migrations.RemoveField(
            model_name="githogpullrequestlayout",
            name="repository",
        ),
        migrations.RemoveField(
            model_name="githogpullrequestlayout",
            name="pr_number",
        ),
        migrations.AlterField(
            model_name="githogpullrequestlayout",
            name="user",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="githog_pr_layout",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
