from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog
from pydantic import BaseModel, Field, field_validator

from posthog.models.utils import UUIDTModel

logger = structlog.get_logger(__name__)


class TaggerType(models.TextChoices):
    LLM = "llm", "LLM"
    HOG = "hog", "Hog"


class TagDefinition(BaseModel):
    """A single tag that can be applied to a generation."""

    name: str = Field(..., min_length=1, max_length=100, description="Tag identifier")
    description: str = Field(default="", max_length=500, description="Optional description to help the LLM tag")

    @field_validator("name")
    @classmethod
    def validate_name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Tag name cannot be empty")
        return v.strip()


class LLMTaggerConfig(BaseModel):
    """Configuration for LLM-based taggers."""

    prompt: str = Field(..., min_length=1, description="Prompt instructing the LLM how to tag")
    tags: list[TagDefinition] = Field(..., min_length=1, description="Available tags")
    min_tags: int = Field(default=0, ge=0, description="Minimum tags to apply")
    max_tags: int | None = Field(default=None, ge=1, description="Maximum tags to apply (null = no limit)")

    @field_validator("prompt")
    @classmethod
    def validate_prompt_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v.strip()

    @field_validator("tags")
    @classmethod
    def validate_unique_tag_names(cls, v: list[TagDefinition]) -> list[TagDefinition]:
        names = [tag.name for tag in v]
        if len(names) != len(set(names)):
            raise ValueError("Tag names must be unique")
        return v


class HogTaggerConfig(BaseModel):
    """Configuration for Hog code taggers."""

    source: str = Field(..., min_length=1, description="Hog source code")
    bytecode: list[Any] = Field(default_factory=list, description="Compiled bytecode (set automatically on save)")
    tags: list[TagDefinition] = Field(..., min_length=1, description="Available tags")

    @field_validator("source")
    @classmethod
    def validate_source_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Source code cannot be empty")
        return v

    @field_validator("tags")
    @classmethod
    def validate_unique_tag_names(cls, v: list[TagDefinition]) -> list[TagDefinition]:
        names = [tag.name for tag in v]
        if len(names) != len(set(names)):
            raise ValueError("Tag names must be unique")
        return v


# Keep TaggerConfig as alias for backwards compatibility with existing LLM taggers
TaggerConfig = LLMTaggerConfig


TAGGER_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    TaggerType.LLM.value: LLMTaggerConfig,
    TaggerType.HOG.value: HogTaggerConfig,
}


def validate_tagger_config(tagger_type: str, tagger_config: dict) -> dict:
    model = TAGGER_CONFIG_MODELS.get(tagger_type)
    if not model:
        raise ValueError(f"Unsupported tagger type: {tagger_type}")
    validated = model(**tagger_config)
    return validated.model_dump(exclude_none=True)


class Tagger(UUIDTModel):
    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["team", "-created_at", "id"]),
            models.Index(fields=["team", "enabled"]),
            models.Index(fields=["model_configuration"], name="llm_analyti_tagger_model_c_idx"),
        ]

    # Core fields
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=False)

    tagger_type = models.CharField(max_length=50, choices=TaggerType.choices, default=TaggerType.LLM)

    # Tagger configuration (stored as JSON, validated per tagger_type)
    tagger_config = models.JSONField(default=dict)

    conditions = models.JSONField(default=list)

    # Model configuration for the LLM
    model_configuration = models.ForeignKey(
        "llm_analytics.LLMModelConfiguration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="taggers",
        db_index=False,
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        from posthog.cdp.filters import compile_filters_bytecode
        from posthog.cdp.validation import compile_hog

        # Validate tagger config based on type
        if self.tagger_config:
            try:
                self.tagger_config = validate_tagger_config(self.tagger_type, self.tagger_config)
            except Exception as e:
                raise ValidationError({"tagger_config": str(e)})

        # Compile Hog source to bytecode
        if self.tagger_type == TaggerType.HOG and self.tagger_config.get("source"):
            try:
                bytecode = compile_hog(self.tagger_config["source"], "destination")
                self.tagger_config["bytecode"] = bytecode
            except Exception as e:
                raise ValidationError({"tagger_config": f"Failed to compile Hog code: {e}"})

        # Compile bytecode for each condition (same pattern as evaluations)
        compiled_conditions = []
        for condition in self.conditions:
            compiled_condition = {**condition}
            filters = {"properties": condition.get("properties", [])}
            compiled = compile_filters_bytecode(filters, self.team)
            compiled_condition["bytecode"] = compiled.get("bytecode")
            compiled_condition["bytecode_error"] = compiled.get("bytecode_error")
            compiled_conditions.append(compiled_condition)

        self.conditions = compiled_conditions
        return super().save(*args, **kwargs)


@receiver(post_save, sender=Tagger)
def tagger_saved(sender, instance, created, **kwargs):
    from posthog.plugins.plugin_server_api import reload_taggers_on_workers

    reload_taggers_on_workers(team_id=instance.team_id, tagger_ids=[str(instance.id)])
