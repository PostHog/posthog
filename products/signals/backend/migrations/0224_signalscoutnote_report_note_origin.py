from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0223_personalinboxranking")]

    operations = [
        migrations.AlterField(
            model_name="signalscoutnote",
            name="origin",
            field=models.CharField(
                choices=[
                    ("human", "Left directly"),
                    ("report_dismissal", "Derived from inbox dismissal feedback"),
                    ("report_discussion", "Derived from inbox discussion feedback"),
                    ("report_feedback", "Derived from inbox report feedback"),
                    ("report_reviewer_correction", "Derived from an inbox reviewer correction"),
                    ("report_note", "Left from an inbox report"),
                ],
                db_default="human",
                default="human",
                max_length=32,
            ),
        ),
    ]
