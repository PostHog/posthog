from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode

tracer = trace.get_tracer(__name__)


def annotate_run_span(team_id: int, run_id: UUID) -> None:
    span = trace.get_current_span()
    span.set_attribute("team_id", team_id)
    span.set_attribute("wizard.run_id", str(run_id))


@contextmanager
def wizard_span(name: str) -> Iterator[Span]:
    # Worker exceptions can contain command output and credentials; export only the error type.
    with tracer.start_as_current_span(name, record_exception=False, set_status_on_exception=False) as span:
        try:
            yield span
        except Exception as error:
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(StatusCode.ERROR)
            raise
