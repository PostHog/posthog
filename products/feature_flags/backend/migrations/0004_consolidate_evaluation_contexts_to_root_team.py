from django.db import migrations


def consolidate_contexts_to_root_team(apps, schema_editor):
    """Move evaluation contexts stored under child-environment teams to the project root team.

    Feature flags persist their contexts under the project root team (RootTeamMixin), but the
    settings endpoints used to create EvaluationContext / TeamDefaultEvaluationContext rows under
    the literal environment team. This consolidates those child-scoped rows under the root team so
    suggestions are consistent across environments, deduping where the root already has the name.
    """
    EvaluationContext = apps.get_model("feature_flags", "EvaluationContext")
    FeatureFlagEvaluationContext = apps.get_model("feature_flags", "FeatureFlagEvaluationContext")
    TeamDefaultEvaluationContext = apps.get_model("feature_flags", "TeamDefaultEvaluationContext")
    Team = apps.get_model("posthog", "Team")

    child_to_parent = dict(Team.objects.filter(parent_team__isnull=False).values_list("id", "parent_team_id"))
    if not child_to_parent:
        return

    for ctx in EvaluationContext.objects.filter(team_id__in=child_to_parent.keys()).iterator():
        root_team_id = child_to_parent[ctx.team_id]
        root_ctx, _ = EvaluationContext.objects.get_or_create(
            team_id=root_team_id,
            name=ctx.name,
            defaults={"hidden_from_suggestions": ctx.hidden_from_suggestions},
        )

        # Repoint flag links before deleting the child context (the FK cascades on delete).
        for link in FeatureFlagEvaluationContext.objects.filter(evaluation_context=ctx):
            if FeatureFlagEvaluationContext.objects.filter(
                feature_flag_id=link.feature_flag_id, evaluation_context=root_ctx
            ).exists():
                link.delete()
            else:
                link.evaluation_context = root_ctx
                link.save(update_fields=["evaluation_context"])

        # Repoint team-default links, deduping on the unique (team, evaluation_context) pair.
        for default in TeamDefaultEvaluationContext.objects.filter(evaluation_context=ctx):
            if TeamDefaultEvaluationContext.objects.filter(team_id=root_team_id, evaluation_context=root_ctx).exists():
                default.delete()
            else:
                default.team_id = root_team_id
                default.evaluation_context = root_ctx
                default.save(update_fields=["team_id", "evaluation_context"])

        ctx.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0003_evaluationcontext_hidden_from_suggestions"),
    ]

    operations = [
        migrations.RunPython(
            consolidate_contexts_to_root_team,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
