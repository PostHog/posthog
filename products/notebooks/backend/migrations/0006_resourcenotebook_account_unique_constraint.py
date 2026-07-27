from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("notebooks", "0005_resourcenotebook_account_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE "posthog_resourcenotebook" ADD CONSTRAINT "posthog_resourcenotebook_notebook_id_group_id_acc_7a017f67_uniq"
                UNIQUE USING INDEX "posthog_resourcenotebook_notebook_id_group_id_acc_7a017f67_uniq"; -- existing-table-constraint-ignore
            """,
            reverse_sql="""
                ALTER TABLE "posthog_resourcenotebook" DROP CONSTRAINT IF EXISTS "posthog_resourcenotebook_notebook_id_group_id_acc_7a017f67_uniq";
            """,
        ),
    ]
