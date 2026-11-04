from ..settings import writer_settings


def writer_team_id() -> int | None:
    writer = writer_settings()
    return writer.team_id if writer else None
