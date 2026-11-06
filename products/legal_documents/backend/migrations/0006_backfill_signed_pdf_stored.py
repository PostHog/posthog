from django.db import migrations


def backfill_signed_pdf_stored(apps, schema_editor):
    # Every already-signed row got its PDF under the old flow, which only
    # flipped status to `signed` after the archive succeeded (PandaDoc webhook)
    # or wrote the PDF synchronously (admin upload). Mark those as stored so the
    # download link keeps working and the reconciliation task ignores them.
    # legal_documents is a small table (hundreds of rows), so a single UPDATE is
    # fine — no batching needed.
    LegalDocument = apps.get_model("legal_documents", "LegalDocument")
    LegalDocument.objects.filter(status="signed").update(signed_pdf_stored=True)


class Migration(migrations.Migration):
    dependencies = [
        ("legal_documents", "0005_legaldocument_signed_pdf_stored"),
    ]

    operations = [
        migrations.RunPython(backfill_signed_pdf_stored, migrations.RunPython.noop),
    ]
