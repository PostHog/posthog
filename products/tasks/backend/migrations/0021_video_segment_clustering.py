import uuid

import django.db.models.deletion
import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0962_webanalyticsfilterpreset"),
        ("tasks", "0020_sandbox_environment"),
    ]

    operations = [
        # Add clustering fields to Task model
        migrations.AddField(
            model_name="task",
            name="cluster_centroid",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.FloatField(),
                blank=True,
                help_text="Embedding centroid for this task's video segment cluster (3072 dimensions)",
                null=True,
                size=None,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="cluster_centroid_updated_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the cluster centroid was last updated",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="priority_score",
            field=models.FloatField(
                blank=True,
                db_index=True,
                help_text="Calculated priority score for ranking tasks",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="distinct_user_count",
            field=models.IntegerField(
                default=0,
                help_text="Number of unique users affected by this issue",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="occurrence_count",
            field=models.IntegerField(
                default=0,
                help_text="Total number of video segment occurrences (cases)",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="last_occurrence_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When this issue was last observed in a video segment",
                null=True,
            ),
        ),
        # Create TaskReference model
        migrations.CreateModel(
            name="TaskReference",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("session_id", models.CharField(max_length=255)),
                ("start_time", models.CharField(max_length=20)),
                ("end_time", models.CharField(max_length=20)),
                ("distinct_id", models.CharField(max_length=255)),
                (
                    "content",
                    models.TextField(
                        blank=True,
                        help_text="The reference description text",
                    ),
                ),
                (
                    "distance_to_centroid",
                    models.FloatField(
                        blank=True,
                        help_text="Cosine distance from this reference to the task's cluster centroid",
                        null=True,
                    ),
                ),
                (
                    "timestamp",
                    models.DateTimeField(
                        blank=True,
                        help_text="Original timestamp of the reference from document_embeddings",
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="references",
                        to="tasks.task",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_task_reference",
            },
        ),
        migrations.AddIndex(
            model_name="taskreference",
            index=models.Index(fields=["task_id", "session_id"], name="posthog_tas_task_id_f3cf5a_idx"),
        ),
        migrations.AddIndex(
            model_name="taskreference",
            index=models.Index(fields=["team_id", "session_id"], name="posthog_tas_team_id_9f1f8c_idx"),
        ),
        migrations.AddIndex(
            model_name="taskreference",
            index=models.Index(fields=["distinct_id"], name="posthog_tas_distinc_5d4e7f_idx"),
        ),
        migrations.AddConstraint(
            model_name="taskreference",
            constraint=models.UniqueConstraint(
                fields=("task_id", "session_id", "start_time", "end_time"),
                name="unique_task_reference",
            ),
        ),
        # Create VideoSegmentClusteringState model
        migrations.CreateModel(
            name="VideoSegmentClusteringState",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                (
                    "last_processed_at",
                    models.DateTimeField(
                        help_text="Timestamp of the most recently processed segment",
                    ),
                ),
                (
                    "last_run_at",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="When the clustering workflow last ran for this team",
                    ),
                ),
                (
                    "segments_processed",
                    models.IntegerField(
                        default=0,
                        help_text="Total number of segments processed in the last run",
                    ),
                ),
                (
                    "clusters_created",
                    models.IntegerField(
                        default=0,
                        help_text="Number of new clusters created in the last run",
                    ),
                ),
                (
                    "tasks_created",
                    models.IntegerField(
                        default=0,
                        help_text="Number of new tasks created in the last run",
                    ),
                ),
                (
                    "tasks_updated",
                    models.IntegerField(
                        default=0,
                        help_text="Number of existing tasks updated in the last run",
                    ),
                ),
            ],
            options={
                "db_table": "posthog_video_segment_clustering_state",
            },
        ),
    ]
