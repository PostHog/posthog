from django.db import migrations, models


class Migration(migrations.Migration):
    """Drop the width from the reviewed change summary, which now carries a clause per owning team.

    varchar(200) to text is binary-coercible in Postgres, so neither table is rewritten and no row
    is read. Each ALTER still takes a brief ACCESS EXCLUSIVE lock while it updates the catalog.
    """

    dependencies = [
        ("stamphog", "0005_index_digest_runs_by_audience"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pullrequest",
            name="summary_line",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="reviewrun",
            name="change_summary",
            field=models.TextField(blank=True, default=""),
        ),
    ]
