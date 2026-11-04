from ..adapters.registry import REGISTRY
from ..logic import intake
from ..settings import writer_settings
from .contracts import DocsCommandRequest, IntakeOutcome
from .enums import DocsRequestSource


def writer_team_id() -> int | None:
    writer = writer_settings()
    return writer.team_id if writer else None


def request_docs_for_pull_request(command: DocsCommandRequest, *, team_id: int) -> IntakeOutcome:
    verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(command)
    return intake.submit(verdict, team_id=team_id)
