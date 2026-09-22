from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("legal_documents", "0004_alter_legaldocument_document_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="legaldocument",
            name="signed_pdf_stored",
            field=models.BooleanField(default=False, db_default=False),
        ),
    ]
