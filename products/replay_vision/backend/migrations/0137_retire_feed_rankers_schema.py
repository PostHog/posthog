from django.db import migrations

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
        untrack_field(
            "replayscanner",
            "search_suggestions",
            "search_suggestions_watermark",
            "search_suggestions_generated_at",
            "search_last_viewed_at",
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
