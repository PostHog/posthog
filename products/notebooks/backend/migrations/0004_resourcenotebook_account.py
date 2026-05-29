import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0005_account"),
        ("notebooks", "0003_add_kernel_timeouts"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="resourcenotebook",
                    name="exactly_one_notebook_related_resource",
                ),
                migrations.AlterUniqueTogether(
                    name="resourcenotebook",
                    unique_together=set(),
                ),
                migrations.AddField(
                    model_name="resourcenotebook",
                    name="account",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notebooks",
                        to="customer_analytics.account",
                    ),
                ),
                migrations.AlterUniqueTogether(
                    name="resourcenotebook",
                    unique_together={("notebook", "group", "account")},
                ),
                migrations.AddConstraint(
                    model_name="resourcenotebook",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("account__isnull", False)),
                        fields=("notebook", "account"),
                        name="unique_notebook_account",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="resourcenotebook",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("group__isnull", False), ("account__isnull", True)),
                            models.Q(("group__isnull", True), ("account__isnull", False)),
                            _connector="OR",
                        ),
                        name="exactly_one_notebook_related_resource",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_resourcenotebook"
                        ADD COLUMN "account_id" uuid NULL
                        CONSTRAINT "posthog_resourcenotebook_account_id_fk"
                        REFERENCES "customer_analytics_account"("id")
                        DEFERRABLE INITIALLY DEFERRED; -- existing-table-constraint-ignore
                        SET CONSTRAINTS "posthog_resourcenotebook_account_id_fk" IMMEDIATE; -- existing-table-constraint-ignore
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_resourcenotebook" DROP COLUMN IF EXISTS "account_id";
                    """,
                ),
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_resourcenotebook" DROP CONSTRAINT IF EXISTS "exactly_one_notebook_related_resource";
                        ALTER TABLE "posthog_resourcenotebook" ADD CONSTRAINT "exactly_one_notebook_related_resource" CHECK ( /* -- existing-table-constraint-ignore */
                            (
                                (group_id IS NOT NULL AND account_id IS NULL) OR /* -- not-null-ignore */
                                (group_id IS NULL AND account_id IS NOT NULL) /* -- not-null-ignore */
                            )
                        ) NOT VALID;
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_resourcenotebook" DROP CONSTRAINT IF EXISTS "exactly_one_notebook_related_resource";
                        ALTER TABLE "posthog_resourcenotebook" ADD CONSTRAINT "exactly_one_notebook_related_resource" CHECK ( /* -- existing-table-constraint-ignore */
                            (group_id IS NOT NULL) /* -- not-null-ignore */
                        ) NOT VALID;
                    """,
                ),
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_resourcenotebook" DROP CONSTRAINT IF EXISTS "posthog_resourcenotebook_notebook_id_group_id_88c0a30b_uniq";
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        )
    ]
