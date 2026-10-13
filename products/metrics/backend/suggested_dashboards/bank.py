"""The curated part of the bank: one JSON file for each well-known source of metrics, such as Envoy or Redis.

A sweep copies the files into the template table, so that curated and generated templates share one table
and one review flow. A file needs no review: it is approved when it lands.
"""

from __future__ import annotations

import json
import hashlib
from functools import cache
from pathlib import Path

from django.db import transaction

from posthog.dataclasses import frozen

from products.metrics.backend.models import MetricsDashboardTemplate
from products.metrics.backend.suggested_dashboards.matching import template_metric_names
from products.metrics.backend.suggested_dashboards.spec import TemplateDefinition

BANK_DIR = Path(__file__).parent / "bank"


@frozen
class CuratedTemplate:
    key: str
    definition: TemplateDefinition
    content_hash: str


@cache
def curated_templates() -> tuple[CuratedTemplate, ...]:
    templates = []
    for path in sorted(BANK_DIR.glob("*.json")):
        raw = path.read_text()
        templates.append(
            CuratedTemplate(
                key=path.stem,
                definition=TemplateDefinition.model_validate(json.loads(raw)),
                content_hash=hashlib.sha256(raw.encode()).hexdigest(),
            )
        )
    return tuple(templates)


def sync_curated_templates() -> int:
    """Bring the template table in line with the bank files. Returns how many rows changed."""
    curated = {template.key: template for template in curated_templates()}
    changed = 0
    with transaction.atomic():
        existing = {
            row.key: row
            for row in MetricsDashboardTemplate.objects.select_for_update().filter(
                source=MetricsDashboardTemplate.Source.CURATED
            )
        }
        for key, template in curated.items():
            row = existing.get(key)
            if row is not None and row.content_hash == template.content_hash:
                continue
            definition = template.definition
            values = {
                "name": definition.name,
                "description": definition.description,
                "source": MetricsDashboardTemplate.Source.CURATED,
                "status": MetricsDashboardTemplate.Status.APPROVED,
                "panels": [panel.model_dump(mode="json") for panel in definition.panels],
                "metric_names": template_metric_names(definition.panels),
                "content_hash": template.content_hash,
            }
            if row is None:
                MetricsDashboardTemplate.objects.create(key=key, **values)
            else:
                for field, value in values.items():
                    setattr(row, field, value)
                row.save()
            changed += 1
        # A file that left the bank stops being suggested, but its row stays for the suggestions that point at it.
        changed += (
            MetricsDashboardTemplate.objects.filter(source=MetricsDashboardTemplate.Source.CURATED)
            .exclude(key__in=list(curated))
            .exclude(status=MetricsDashboardTemplate.Status.REJECTED)
            .update(status=MetricsDashboardTemplate.Status.REJECTED)
        )
    return changed
