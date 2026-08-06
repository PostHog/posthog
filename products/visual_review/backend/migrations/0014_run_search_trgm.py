from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    # Free-text runs search uses pg_trgm word_similarity over branch / run_type.
    # visual_review runs on its own Postgres database, so the extension has to be
    # enabled here — the main DB's pg_trgm (posthog migration 0034) doesn't reach it.
    # CREATE EXTENSION IF NOT EXISTS is idempotent, so this is safe on DBs that already have it.
    dependencies = [
        ("visual_review", "0013_run_is_partial"),
    ]

    operations = [
        TrigramExtension(),
    ]
