from django.db import migrations, models

import products.legal_documents.backend.models


def _populate_webhook_secrets(apps, schema_editor):
    """
    Django's AddField with a callable default calls the callable once and reuses
    the value for every existing row. The LegalDocument table is brand-new (see
    0001_initial_migration), so this is defensive: if any rows exist at apply
    time we ensure each gets its own unique secret.
    """
    LegalDocument = apps.get_model("legal_documents", "LegalDocument")
    for doc in LegalDocument.objects.all().iterator():
        doc.webhook_secret = products.legal_documents.backend.models._generate_webhook_secret()
        doc.save(update_fields=["webhook_secret"])


class Migration(migrations.Migration):
    dependencies = [
        ("legal_documents", "0001_initial_migration"),
    ]

    operations = [
        migrations.AddField(
            model_name="legaldocument",
            name="signed_document_url",
            field=models.URLField(blank=True, max_length=2048),
        ),
        migrations.AddField(
            model_name="legaldocument",
            name="status",
            field=models.CharField(
                choices=[
                    ("submitted_for_signature", "Submitted for signature"),
                    ("signed", "Signed"),
                ],
                default="submitted_for_signature",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="legaldocument",
            name="webhook_secret",
            field=models.CharField(
                default=products.legal_documents.backend.models._generate_webhook_secret,
                max_length=64,
            ),
        ),
        migrations.RunPython(_populate_webhook_secrets, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
