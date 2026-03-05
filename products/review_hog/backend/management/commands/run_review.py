import asyncio

from django.core.management.base import BaseCommand

from products.review_hog.backend.runner import run_review


class Command(BaseCommand):
    help = "Run a code review agent in a sandbox. Supports multiple prompts concurrently."

    def add_arguments(self, parser):
        parser.add_argument(
            "prompts",
            nargs="+",
            help="One or more review prompts. Each spawns a separate sandbox.",
        )
        parser.add_argument(
            "--branch",
            default="master",
            help="Git branch to check out before reviewing (default: master)",
        )

    def handle(self, *args, **options):
        prompts = options["prompts"]
        branch = options["branch"]

        self.stdout.write(f"Launching {len(prompts)} review(s) on branch '{branch}'...")

        results = asyncio.run(self._run_all(prompts, branch))

        for i, (prompt, result) in enumerate(zip(prompts, results)):
            self.stdout.write(self.style.HTTP_INFO(f"\n{'=' * 80}"))
            self.stdout.write(self.style.HTTP_INFO(f"Review {i + 1}: {prompt[:80]}"))
            self.stdout.write(self.style.HTTP_INFO(f"{'=' * 80}"))
            if isinstance(result, Exception):
                self.stdout.write(self.style.ERROR(f"Error: {result}"))
            else:
                self.stdout.write(result)

    async def _run_all(self, prompts: list[str], branch: str) -> list[str | Exception]:
        tasks = [self._run_one(prompt, branch) for prompt in prompts]
        return await asyncio.gather(*tasks)

    @staticmethod
    async def _run_one(prompt: str, branch: str) -> str | Exception:
        try:
            return await run_review(prompt, branch=branch)
        except Exception as e:
            return e
