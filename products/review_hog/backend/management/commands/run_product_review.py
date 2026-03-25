import asyncio
import logging

from django.core.management.base import BaseCommand

from products.review_hog.backend.reviewer.product_review_run import main

# Ensure review_hog loggers output to console
_review_logger = logging.getLogger("products.review_hog")
_review_logger.setLevel(logging.INFO)
if not _review_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    _review_logger.addHandler(_handler)


class Command(BaseCommand):
    help = "Run a product-aware PR review using sandbox agents"

    def add_arguments(self, parser):
        parser.add_argument(
            "--pr-url",
            required=True,
            type=str,
            help="GitHub PR URL (e.g., https://github.com/PostHog/posthog/pull/34633)",
        )

    def handle(self, *args, **options):
        try:
            asyncio.run(main(pr_url=options["pr_url"]))
        except Exception:
            import traceback

            traceback.print_exc()
            raise
