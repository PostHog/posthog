"""Dimension 5: generated API client adoption."""

from __future__ import annotations

from pathlib import Path

from ..ts_helpers import codegen_adoption, codegen_call_sites
from . import scores


def score_codegen(product_dir: Path) -> scores.DimensionScore:
    """Frontend code generation adoption.

    Measures whether the product uses the generated API client instead of
    manual api.* calls. Having generated/api.ts is free (hogli build:openapi
    creates it for everyone) — what matters is actual usage.

    Score = percentage of API calls using generated client:
      100 * generated_used / (generated_used + manual_calls)
    """
    frontend_dir = product_dir / "frontend"
    if not frontend_dir.exists():
        return scores.DimensionScore("codegen", 0, "no frontend", applicable=False)

    metrics = codegen_adoption(frontend_dir)
    available = metrics["generated_available"]
    used = metrics["generated_used"]
    manual = metrics["manual_calls"]

    # No frontend API usage at all — still applicable, just 0
    if available == 0 and manual == 0:
        return scores.DimensionScore("codegen", 0, "no API usage")

    total_calls = used + manual

    if total_calls > 0:
        score = round(100 * used / total_calls)
        detail = f"{score}% codegen ({used} generated, {manual} manual)"
    else:
        score = 0
        detail = "no API usage"

    next_steps: list[str] = []
    skills: list[str] = []
    evidence: list[tuple[str, list[str]]] = []
    if score < 100 and manual > 0:
        next_steps.append(
            f"Replace the {manual} manual `api.*`/`api.<entity>.<verb>` call(s) listed below "
            f"with the generated client (each one shows the matching generated function)."
        )
        next_steps.append(
            "For sites marked `(no match)`, the backend viewset is missing schema annotations "
            "(`@validated_request` or `@extend_schema`) or the serializer field types are too "
            "loose. Fix the backend, run `hogli build:openapi`, then migrate the call."
        )
        sites = codegen_call_sites(frontend_dir)
        if sites:
            items = [
                f"{site.file}:{site.line}  {site.verb}  "
                + (f"→ {site.generated_equivalent}" if site.generated_equivalent else "(no match)")
                for site in sites
            ]
            evidence.append(("call sites", items))
        skills.append("/adopting-generated-api-types")
        skills.append("/improving-drf-endpoints")
    elif score < 100 and total_calls > 0:
        next_steps.append(
            "All API calls are accounted for but none use the generated client. Run "
            "`hogli build:openapi` and migrate to the generated functions in "
            "products/<name>/frontend/generated/api.ts."
        )
        skills.append("/adopting-generated-api-types")

    return scores.DimensionScore("codegen", score, detail, next_steps=next_steps, skills=skills, evidence=evidence)
