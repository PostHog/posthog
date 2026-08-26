from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0003_message_suppression"),
    ]

    operations = [
        # Choices-only change, so the schema editor emits no SQL — `choices` is in Django's
        # `Field.non_db_attrs`. It exists to keep migration state in step with the model.
        # "COMPLAINT" is 9 characters, well inside the column's existing varchar(16).
        migrations.AlterField(
            model_name="messagesuppression",
            name="source",
            field=models.CharField(
                choices=[("BOUNCE", "Bounce"), ("COMPLAINT", "Complaint"), ("MANUAL", "Manual")],
                default="BOUNCE",
                max_length=16,
            ),
        ),
    ]
