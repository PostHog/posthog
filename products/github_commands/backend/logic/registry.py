"""The commands `@posthog` understands on a pull request.

To add a command, write a handler that calls the target product's facade, then declare it here.
Give it `access` when the target product has a resource in PostHog access control, at the level
the product's own API asks for the same action. Dispatch applies every check before the handler runs.
"""

from collections.abc import Mapping

from .commands import CommandSpec, ResourceAccess
from .handlers import handle_loop, handle_qa, handle_review, handle_stamp

# Answered by dispatch itself: it needs no PostHog account, project or pull request state.
HELP_VERB = "help"


COMMANDS: Mapping[str, CommandSpec] = {
    spec.verb: spec
    for spec in (
        CommandSpec(
            verb="review",
            summary="Start a PostHog Review of this pull request. Add `flash` for a quicker review.",
            usage="@posthog review [flash]",
            handler=handle_review,
            accepts_argument=True,
        ),
        CommandSpec(
            verb="stamp",
            summary="Ask Stamphog to review this pull request. Stamphog decides whether to approve.",
            usage="@posthog stamp",
            handler=handle_stamp,
            access=ResourceAccess(resource="stamphog", level="editor"),
        ),
        CommandSpec(
            verb="qa",
            summary="Run frontend QA on this pull request in PostHog Code and post a report.",
            usage="@posthog qa [what to focus on]",
            handler=handle_qa,
            accepts_argument=True,
        ),
        CommandSpec(
            verb="loop",
            summary="Run one of your own Loops with this pull request as its input.",
            usage="@posthog loop <loop name>",
            handler=handle_loop,
            accepts_argument=True,
        ),
    )
}


def help_text() -> str:
    rows = "\n".join(
        [f"| `{spec.usage}` | {spec.summary} |" for spec in COMMANDS.values()]
        + ["| `@posthog help` | List these commands. |"]
    )
    return f"Commands you can use on a pull request:\n\n| Command | What it does |\n| --- | --- |\n{rows}"
