import asyncio
import traceback

from django.core.management.base import BaseCommand

from pydantic import BaseModel

from products.tasks.backend.services.sandbox_prompt_executor import run_sandbox_agent_get_structured_output
from products.tasks.backend.services.sandbox_prompt_runner import resolve_sandbox_context_for_local_dev


class PromptAnswer(BaseModel):
    answer: str


class Command(BaseCommand):
    help = "Run a custom prompt in a sandbox agent and validate structured output (e2e smoke test)"

    def add_arguments(self, parser):
        parser.add_argument(
            "prompt",
            type=str,
            help='The prompt to send to the sandbox agent, e.g. "tell me a joke about monkeys"',
        )
        parser.add_argument(
            "--repository",
            type=str,
            default="posthog/posthog",
            help="GitHub repository in org/repo format (default: posthog/posthog)",
        )
        parser.add_argument(
            "--branch",
            type=str,
            default="master",
            help="Branch to check out in the sandbox (default: master)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Stream all raw log lines instead of only agent messages",
        )

    def handle(self, *args, **options):
        prompt = options["prompt"]
        repository = options["repository"]
        branch = options["branch"]
        verbose = options["verbose"]

        self.stdout.write(f"Resolving sandbox context for repository: {repository}")
        try:
            context = resolve_sandbox_context_for_local_dev(repository)
        except RuntimeError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return

        self.stdout.write(f"  team_id={context.team_id}, user_id={context.user_id}")
        self.stdout.write(f"  branch={branch}")
        self.stdout.write(f"  prompt: {prompt[:120]}")
        self.stdout.write("")

        full_prompt = (
            f"{prompt}\n\n"
            "Respond with a JSON object inside a ```json``` code block with a single key "
            '"answer" containing your response as a string.'
        )

        self.stdout.write(self.style.WARNING("Starting sandbox agent..."))
        self.stdout.write("")

        try:
            result = asyncio.run(
                run_sandbox_agent_get_structured_output(
                    prompt=full_prompt,
                    context=context,
                    model_to_validate=PromptAnswer,
                    branch=branch,
                    step_name="run_sandbox_prompt",
                    verbose=verbose,
                    output_fn=self.stdout.write,
                )
            )

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("=" * 60))
            self.stdout.write(self.style.SUCCESS("RESULT"))
            self.stdout.write(self.style.SUCCESS("=" * 60))
            self.stdout.write(f"answer: {result.answer}")

        except Exception as e:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(f"Failed: {e}"))
            self.stdout.write(traceback.format_exc())
            raise
