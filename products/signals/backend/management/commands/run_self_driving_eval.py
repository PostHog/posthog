from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.signals.eval.self_driving.eval_selfdriving import BraintrustEvalError
from products.signals.eval.self_driving.harness.drive import DEFAULT_WORKSPACE, all_task_ids, drive, format_eval_summary


class Command(BaseCommand):
    help = "Run the synthetic end-to-end Signals research and implementation eval."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--task",
            action="append",
            choices=all_task_ids(),
            dest="task_ids",
            help="Run one task. Repeat the option to run more than one task.",
        )
        parser.add_argument("--trials", type=int, default=1, help="Number of trials per task.")
        parser.add_argument("--parallelism", type=int, default=2, help="Maximum number of concurrent task runs.")
        parser.add_argument(
            "--workspace", default=str(DEFAULT_WORKSPACE), help="Directory for repositories and results."
        )
        parser.add_argument("--research-timeout", type=float, default=3600, help="Research timeout in seconds.")
        parser.add_argument(
            "--implementation-timeout", type=float, default=2700, help="Implementation timeout in seconds."
        )
        parser.add_argument("--experiment-name", help="Braintrust experiment name.")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("This command can only run with DEBUG enabled.")
        if options["trials"] < 1:
            raise CommandError("--trials must be at least 1.")
        if options["parallelism"] < 1:
            raise CommandError("--parallelism must be at least 1.")

        try:
            result = drive(
                task_ids=options["task_ids"],
                trials=options["trials"],
                parallelism=options["parallelism"],
                workspace=options["workspace"],
                research_timeout_s=options["research_timeout"],
                implementation_timeout_s=options["implementation_timeout"],
                experiment_name=options["experiment_name"],
            )
        except BraintrustEvalError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(self.style.SUCCESS("Self-driving eval finished."))
        self.stdout.write(format_eval_summary(result, Path(options["workspace"]) / "results"))
