from typing import Any

from products.growth.backend.models import EnrichmentPromptConfig


def ensure_prompt_config(
    *,
    name: str,
    version: str,
    prompt_text: str,
    model: str,
    input_fields: list[str],
    output_fields: list[dict[str, Any]],
) -> bool:
    # Same two-step shape as growth migration 0006: insert inactive so the
    # growth_prompt_config_one_active constraint can't collide, promote only
    # when no other active config exists.
    config, _ = EnrichmentPromptConfig.objects.get_or_create(
        name=name,
        version=version,
        defaults={
            "prompt_text": prompt_text,
            "model": model,
            "input_fields": input_fields,
            "output_fields": output_fields,
            "is_active": False,
        },
    )
    other_active_exists = (
        EnrichmentPromptConfig.objects.filter(name=name, is_active=True).exclude(pk=config.pk).exists()
    )
    if config.is_active or other_active_exists:
        return False
    config.is_active = True
    config.save(update_fields=["is_active"])
    return True
