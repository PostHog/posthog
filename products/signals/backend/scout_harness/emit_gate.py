from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun, SignalSourceConfig


def preflight_emit_gates(team: Team, run: SignalScoutRun) -> str | None:
    config_id = (
        SignalScoutRun.all_teams.filter(pk=run.pk, team_id=team.id).values_list("scout_config_id", flat=True).first()
    )
    if config_id is None:
        return "scout_config_missing"
    config = SignalScoutConfig.all_teams.filter(pk=config_id).first()
    if config is None:
        return "scout_config_missing"
    if not config.emit:
        return "scout_emit_disabled"
    approved = (
        Team.objects.filter(pk=team.id).values_list("organization__is_ai_data_processing_approved", flat=True).first()
    )
    if approved is not True:
        return "ai_processing_not_approved"
    if not SignalSourceConfig.is_source_enabled(
        team.id,
        SignalSourceConfig.SourceProduct.SIGNALS_SCOUT.value,
        SignalSourceConfig.SourceType.CROSS_SOURCE_ISSUE.value,
    ):
        return "source_disabled"
    return None
