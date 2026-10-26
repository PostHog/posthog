from posthog.clickhouse.client.connection import ClickHouseUser


async def implementation_may_resume(
    *, team_id: int, report_id: str, task_id: str, user_id: int, repository: str
) -> bool:
    from products.signals.backend.auto_start import (  # noqa: PLC0415 - breaks the Signals/Tasks autostart cycle
        ImplementationResume,
        maybe_autostart_from_report_artefacts,
    )

    outcome = await maybe_autostart_from_report_artefacts(
        team_id=team_id,
        report_id=report_id,
        github_recovery=True,
        resume=ImplementationResume(task_id=task_id, user_id=user_id, repository=repository),
        ch_user=ClickHouseUser.SIGNALS,
    )
    return outcome.status == "queued"
