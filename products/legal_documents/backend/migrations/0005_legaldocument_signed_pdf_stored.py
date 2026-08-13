from django.db import migrations, models


def backfill_signed_pdf_stored(apps, schema_editor):
    # Every already-signed row got its PDF under the old flow, which only
    # flipped status to `signed` after the archive succeeded (PandaDoc webhook)
    # or wrote the PDF synchronously (admin upload). Mark those as stored so the
    # download link keeps working and the reconciliation task ignores them.
    LegalDocument = apps.get_model("legal_documents", "LegalDocument")
    LegalDocument.objects.filter(status="signed").update(signed_pdf_stored=True)


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
        migrations.RunPython(backfill_signed_pdf_stored, migrations.RunPython.noop),
    ]
