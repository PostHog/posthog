import re
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

import yaml

from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Matches the slug in a posthog.com source docsUrl, e.g.
# https://posthog.com/docs/cdp/sources/active-campaign -> "active-campaign".
DOCS_URL_SLUG = re.compile(r"/docs/cdp/sources/([^/?#]+)")

FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


class Command(BaseCommand):
    help = (
        "Audit data warehouse source docs against the source registry: every source whose docsUrl "
        "points at /docs/cdp/sources/<slug> must have a matching <slug>.{md,mdx} file, and every "
        "doc's `sourceId` frontmatter must be a real ExternalDataSourceType value. Exits non-zero "
        "on any mismatch so it can gate the docs/source-implementation workflows."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--docs-dir",
            required=True,
            help="Path to posthog.com/contents/docs/cdp/sources in a local posthog.com checkout.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        docs_dir = Path(options["docs_dir"])
        if not docs_dir.is_dir():
            raise CommandError(f"docs dir does not exist: {docs_dir}")

        existing_slugs = {p.stem for p in docs_dir.glob("*.md")} | {p.stem for p in docs_dir.glob("*.mdx")}
        valid_source_ids = {str(member.value) for member in ExternalDataSourceType}

        errors: list[str] = []

        # 1. Every source docsUrl that targets our docs must resolve to a committed file.
        for source_type, source in SourceRegistry.get_all_sources().items():
            docs_url = source.get_source_config.docsUrl
            if not docs_url:
                continue
            match = DOCS_URL_SLUG.search(docs_url)
            if not match:
                continue  # external docs (e.g. a vendor URL) — nothing to verify here
            slug = match.group(1)
            if slug not in existing_slugs:
                errors.append(f"{source_type}: docsUrl points at '{slug}' but no {slug}.md(x) exists")

        # 2. Every doc's sourceId frontmatter must be a real source.
        for doc in sorted([*docs_dir.glob("*.md"), *docs_dir.glob("*.mdx")]):
            frontmatter = FRONTMATTER.match(doc.read_text())
            if not frontmatter:
                continue
            parsed = yaml.safe_load(frontmatter.group(1)) or {}
            source_id = parsed.get("sourceId")
            if source_id and source_id not in valid_source_ids:
                errors.append(f"{doc.name}: sourceId '{source_id}' is not a valid ExternalDataSourceType")

        if errors:
            self.stderr.write(self.style.ERROR(f"Found {len(errors)} source-doc mismatch(es):"))
            for error in errors:
                self.stderr.write(f"  - {error}")
            raise CommandError("source docs are out of sync with the source registry")

        self.stdout.write(self.style.SUCCESS(f"OK: {len(existing_slugs)} source docs consistent with the registry"))
