from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0032_fingerprint_covering_index"),
    ]

    operations = [
        # `unique_fingerprint_for_team_covering` from 0032 enforces the same uniqueness, so keeping
        # this constraint only costs a second index write on every fingerprint insert. The drop takes
        # a brief ACCESS EXCLUSIVE lock; apply 0032 on its own first if the deploy must stage them.
        migrations.RemoveConstraint(
            model_name="errortrackingissuefingerprintv2",
            name="unique_fingerprint_for_team",
        ),
    ]
