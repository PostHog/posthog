from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("legal_documents", "0002_legaldocument_pandadoc_integration"),
    ]

    operations = [
        # Signed PDFs now live in object storage under legal_documents/{id}.pdf;
        # the URL is generated on demand via a presigned proxy endpoint rather
        # than persisted on the row.
        migrations.RemoveField(
            model_name="legaldocument",
            name="signed_document_url",
        ),
    ]
