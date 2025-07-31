# Generated migration for repository scoping system

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0001_initial'),
        ('issue_tracker', '0006_issueprogress'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='repository_scope',
            field=models.CharField(
                choices=[
                    ('single', 'Single Repository'),
                    ('multiple', 'Multiple Repositories'),
                    ('smart_select', 'Smart Select')
                ],
                default='single',
                help_text='How repositories are selected for this issue',
                max_length=20
            ),
        ),
        migrations.AddField(
            model_name='issue',
            name='github_integration',
            field=models.ForeignKey(
                blank=True,
                help_text='Primary GitHub integration for this issue',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='posthog.integration'
            ),
        ),
        migrations.AddField(
            model_name='issue',
            name='repository_config',
            field=models.JSONField(
                default=dict,
                help_text='Repository configuration based on scope type'
            ),
        ),
        # Note: Keeping existing github_branch and github_pr_url fields for backward compatibility
    ]