import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0006_messagetemplate_transactional_hog_flow_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="messagetemplate",
            name="content_hash",
            field=models.CharField(
                blank=True,
                help_text="Hash of the published subject, preheader, HTML and text, as `v1:` and 64 hex characters.",
                max_length=80,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="key",
            field=models.CharField(
                blank=True,
                help_text="Client-chosen identifier, unique within this environment among templates that are not deleted. Letters, numbers, hyphens (-) and underscores (_) only.",
                max_length=400,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="managed_by",
            field=models.CharField(
                blank=True,
                choices=[("gui", "GUI"), ("code", "Code")],
                help_text="Who owns the template content: `gui` for the PostHog app, `code` for uploads from a repository. Empty means `gui`.",
                max_length=400,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="source_path",
            field=models.CharField(
                blank=True,
                help_text="Path of the template file in the source repository.",
                max_length=400,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="source_ref",
            field=models.CharField(
                blank=True,
                help_text="Commit or branch of the last upload.",
                max_length=400,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="source_repository",
            field=models.CharField(
                blank=True,
                help_text="Repository the template was last uploaded from, such as `github.com/example/app`.",
                max_length=400,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="superseded_content_hashes",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=80),
                blank=True,
                null=True,
                size=None,
            ),
        ),
    ]
