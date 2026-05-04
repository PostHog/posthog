from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("legal_documents", "0001_initial_migration"),
    ]

    operations = [
        # New column: PandaDoc document uuid, used as the join key for inbound webhooks.
        migrations.AddField(
            model_name="legaldocument",
            name="pandadoc_document_id",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        # Drop Zapier-era pre-shared secret — PandaDoc webhooks authenticate via HMAC now.
        migrations.RemoveField(
            model_name="legaldocument",
            name="webhook_secret",
        ),
        # DPA mode is preview-only in the UI and no longer persisted.
        migrations.RemoveField(
            model_name="legaldocument",
            name="dpa_mode",
        ),
        # PandaDoc's Client.Email is populated from the recipient alone — no need to
        # collect or persist representative name/title.
        migrations.RemoveField(
            model_name="legaldocument",
            name="representative_name",
        ),
        migrations.RemoveField(
            model_name="legaldocument",
            name="representative_title",
        ),
        # Address is now required on every document (PandaDoc's Client.StreetAddress
        # is referenced by both templates).
        migrations.AlterField(
            model_name="legaldocument",
            name="company_address",
            field=models.CharField(max_length=512),
        ),
    ]
