# Generated migration for IssueProgress model

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0001_initial'),  # Replace with actual posthog migration
        ('issue_tracker', '0005_githubintegration'),
    ]

    operations = [
        migrations.CreateModel(
            name='IssueProgress',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('started', 'Started'), ('in_progress', 'In Progress'), ('completed', 'Completed'), ('failed', 'Failed')], default='started', max_length=20)),
                ('current_step', models.CharField(blank=True, help_text='Current step being executed', max_length=255)),
                ('total_steps', models.IntegerField(default=0, help_text='Total number of steps if known')),
                ('completed_steps', models.IntegerField(default=0, help_text='Number of completed steps')),
                ('output_log', models.TextField(blank=True, help_text='Live output from Claude Code execution')),
                ('error_message', models.TextField(blank=True, help_text='Error message if execution failed')),
                ('workflow_id', models.CharField(blank=True, help_text='Temporal workflow ID', max_length=255)),
                ('workflow_run_id', models.CharField(blank=True, help_text='Temporal workflow run ID', max_length=255)),
                ('activity_id', models.CharField(blank=True, help_text='Temporal activity ID', max_length=255)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('issue', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='progress_logs', to='issue_tracker.issue')),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='posthog.team')),
            ],
            options={
                'db_table': 'posthog_issue_progress',
                'ordering': ['-created_at'],
            },
        ),
    ]
