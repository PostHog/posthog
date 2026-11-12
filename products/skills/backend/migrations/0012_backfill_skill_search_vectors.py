from django.db import migrations

BATCH_SIZE = 100


# Only the latest, live, ordinary skills are searchable, which is a small fraction of the table. The
# other rows keep a NULL vector. They become searchable only as a new version row, which the trigger
# fills on insert. A searchable row with a NULL vector still matches on its name, description and file
# paths, but not on its body or file contents. Each batch commits on its own, and the IS NULL filters
# make a rerun after a failure skip the rows that are already done.
def backfill(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM llm_analytics_llmskill WHERE is_latest AND NOT deleted AND category = '' ORDER BY id"
        )
        skill_ids = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            "SELECT id FROM llm_analytics_llmskillfile WHERE skill_id = ANY(%s) ORDER BY id",
            [skill_ids],
        )
        file_ids = [row[0] for row in cursor.fetchall()]

    for sql, ids in (
        (
            "UPDATE llm_analytics_llmskill SET search_vector = llm_skill_search_vector(body) "
            "WHERE id = ANY(%s) AND search_vector IS NULL",
            skill_ids,
        ),
        (
            "UPDATE llm_analytics_llmskillfile SET search_vector = llm_skill_search_vector(content) "
            "WHERE id = ANY(%s) AND search_vector IS NULL",
            file_ids,
        ),
    ):
        for start in range(0, len(ids), BATCH_SIZE):
            with schema_editor.connection.cursor() as cursor:
                cursor.execute(sql, [ids[start : start + BATCH_SIZE]])


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("skills", "0011_skill_search_vectors"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop, elidable=True),
    ]
