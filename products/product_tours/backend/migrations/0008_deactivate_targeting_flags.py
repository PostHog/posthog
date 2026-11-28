from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("product_tours", "0001_squash_2026_11_02_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                UPDATE posthog_featureflag
                SET active = false
                WHERE active
                  AND id IN (
                      SELECT internal_targeting_flag_id
                      FROM product_tours_producttour
                      WHERE internal_targeting_flag_id IS NOT NULL
                  );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
