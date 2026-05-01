from django.db import migrations, models


def copy_experiment_fields(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    TeamExperimentsConfig = apps.get_model("experiments", "TeamExperimentsConfig")

    teams_with_config = Team.objects.filter(
        models.Q(experiment_recalculation_time__isnull=False)
        | models.Q(default_experiment_confidence_level__isnull=False)
        | (
            models.Q(default_experiment_stats_method__isnull=False)
            & ~models.Q(default_experiment_stats_method="bayesian")
        )
    )

    configs = []
    for team in teams_with_config.only(
        "id",
        "experiment_recalculation_time",
        "default_experiment_confidence_level",
        "default_experiment_stats_method",
    ).iterator(chunk_size=1000):
        configs.append(
            TeamExperimentsConfig(
                team_id=team.id,
                experiment_recalculation_time=team.experiment_recalculation_time,
                default_experiment_confidence_level=team.default_experiment_confidence_level,
                default_experiment_stats_method=team.default_experiment_stats_method,
            )
        )
        if len(configs) >= 1000:
            TeamExperimentsConfig.objects.bulk_create(configs, ignore_conflicts=True)
            configs = []

    if configs:
        TeamExperimentsConfig.objects.bulk_create(configs, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0004_team_experiments_config"),
    ]

    operations = [
        migrations.RunPython(copy_experiment_fields, migrations.RunPython.noop),
    ]
