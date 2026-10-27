from django.db import migrations
from django.db.migrations.state import ProjectState

from posthog.migration_helpers import untrack_field

# Databases created before the lens tables were renamed still carry these names; fresh databases already use the new ones.
_LEGACY_INDEX_NAMES = [
    ("replay_vision_replaylens_pkey", "replay_vision_replayscanner_pkey"),
    ("replay_vision_replaylens_team_id_6cbf8851", "replay_vision_replayscanner_team_id_5b48156f"),
    ("replay_vision_replaylens_created_by_id_d748ea54", "replay_vision_replayscanner_created_by_id_f7e76528"),
    ("replay_vision_replaylensobservation_pkey", "replay_vision_replayobservation_pkey"),
    (
        "replay_vision_replaylensob_triggered_by_user_id_55bd1882",
        "replay_vision_replayobservation_triggered_by_user_id_f913652f",
    ),
]


class _RemoveFieldIfTracked(migrations.RemoveField):
    """The pre-squash history drops three of these fields from state when the squash recreates the model."""

    def state_forwards(self, app_label: str, state: ProjectState) -> None:
        if self.name in state.models[app_label, self.model_name_lower].fields:
            super().state_forwards(app_label, state)


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0136_retire_search_suggestion_columns"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[f'ALTER INDEX IF EXISTS "{old}" RENAME TO "{new}"' for old, new in _LEGACY_INDEX_NAMES],
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RenameIndex(
            model_name="replayobservationusage",
            new_name="rlou_org_observed_idx",
            old_name="replay_visi_organiz_a84ed4_idx",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                _RemoveFieldIfTracked(model_name="replayscanner", name=name)
                for name in (
                    "search_suggestions",
                    "search_suggestions_watermark",
                    "search_suggestions_generated_at",
                    "search_last_viewed_at",
                )
            ],
        ),
        untrack_field("replayobservationmedia", "rec_start_ms"),
        untrack_field(
            "teamreplayvisionconfig",
            "search_suggestions",
            "search_suggestions_sources",
            "search_suggestions_watermark",
            "search_suggestions_generated_at",
        ),
    ]
