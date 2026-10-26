from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations
from django.db.models.functions import Upper


class Migration(migrations.Migration):
    dependencies = [("signals", "0196_signalreport_tags")]

    # ALTER INDEX changes the storage parameter in place, so the indexes are not rebuilt.
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        # fastupdate takes ACCESS EXCLUSIVE on the index, and queries that plan against
                        # the table queue behind a waiting request. Fail fast and let bin/migrate retry.
                        "SET LOCAL lock_timeout = '5s'",
                        'ALTER INDEX IF EXISTS "signal_scratchpad_content_trgm" SET (fastupdate = off)',
                        'ALTER INDEX IF EXISTS "signal_scratchpad_key_trgm" SET (fastupdate = off)',
                    ],
                    reverse_sql=[
                        "SET LOCAL lock_timeout = '5s'",
                        'ALTER INDEX IF EXISTS "signal_scratchpad_content_trgm" SET (fastupdate = on)',
                        'ALTER INDEX IF EXISTS "signal_scratchpad_key_trgm" SET (fastupdate = on)',
                    ],
                ),
            ],
            state_operations=[
                migrations.RemoveIndex(model_name="signalscratchpad", name="signal_scratchpad_content_trgm"),
                migrations.RemoveIndex(model_name="signalscratchpad", name="signal_scratchpad_key_trgm"),
                migrations.AddIndex(
                    model_name="signalscratchpad",
                    index=GinIndex(
                        OpClass(Upper("content"), name="gin_trgm_ops"),
                        name="signal_scratchpad_content_trgm",
                        fastupdate=False,
                    ),
                ),
                migrations.AddIndex(
                    model_name="signalscratchpad",
                    index=GinIndex(
                        OpClass(Upper("key"), name="gin_trgm_ops"),
                        name="signal_scratchpad_key_trgm",
                        fastupdate=False,
                    ),
                ),
            ],
        ),
    ]
