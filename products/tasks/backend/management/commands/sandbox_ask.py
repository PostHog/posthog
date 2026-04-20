import asyncio
import traceback

from django.core.management.base import BaseCommand

from pydantic import BaseModel

from products.tasks.backend.services.custom_prompt_executor import run_sandbox_agent_get_structured_output
from products.tasks.backend.services.custom_prompt_runner import run_prompt
from products.tasks.backend.services.dev_sandbox_context import resolve_sandbox_context_for_local_dev


class StructuredAnswer(BaseModel):
    answer: str


class Command(BaseCommand):
    help = (
        "Ask a question about a repository via a sandbox agent. "
        "The agent clones the repo and answers using the full codebase as context."
        "Could be used as a smoke-test during development."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "prompt",
            type=str,
            help='Question or instruction, e.g. "how does the auth middleware work?"',
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
            "--json",
            action="store_true",
            dest="json_mode",
            help='Return structured JSON output ({"answer": "..."}), useful for programmatic consumption',
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
        json_mode = options["json_mode"]
        verbose = options["verbose"]

        self.stdout.write(f"Repository: {repository} (branch: {branch})")

        try:
            context = resolve_sandbox_context_for_local_dev(repository)
        except RuntimeError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return

        self.stdout.write(f"Prompt: {prompt[:200]}")
        self.stdout.write("")

        if json_mode:
            self._run_json_mode(prompt, context, branch, verbose)
        else:
            self._run_text_mode(prompt, context, branch, verbose)

    def _run_text_mode(self, prompt, context, branch, verbose):
        try:
            last_message, _ = asyncio.run(
                run_prompt(
                    prompt=prompt,
                    context=context,
                    branch=branch,
                    step_name="sandbox_ask",
                    verbose=verbose,
                    output_fn=self.stdout.write,
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed: {e}"))
            self.stdout.write(traceback.format_exc())
            raise

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(last_message)

    def _run_json_mode(self, prompt, context, branch, verbose):
        full_prompt = (
            f"{prompt}\n\n"
            "Respond with a JSON object inside a ```json``` code block with a single key "
            '"answer" containing your response as a string.'
        )

        try:
            result = asyncio.run(
                run_sandbox_agent_get_structured_output(
                    prompt=full_prompt,
                    context=context,
                    model_to_validate=StructuredAnswer,
                    branch=branch,
                    step_name="sandbox_ask",
                    verbose=verbose,
                    output_fn=self.stdout.write,
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed: {e}"))
            self.stdout.write(traceback.format_exc())
            raise

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(result.answer)
