from django.db import models

from pydantic import BaseModel, Field, field_validator


class EvaluationType(models.TextChoices):
    """How the evaluation is performed"""

    LLM_JUDGE = "llm_judge", "LLM as a judge"


class OutputType(models.TextChoices):
    """What type of result is expected"""

    BOOLEAN = "boolean", "Boolean (Pass/Fail)"


class LLMJudgeConfig(BaseModel):
    """Configuration for LLM judge evaluations"""

    prompt: str = Field(..., min_length=1, description="Evaluation criteria prompt")

    @field_validator("prompt")
    @classmethod
    def validate_prompt_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v.strip()


class BooleanOutputConfig(BaseModel):
    """Configuration for boolean output type"""

    # Currently no specific config needed for boolean output
    # This is a placeholder for future extensions
    pass


# Mapping: (evaluation_type, output_type) -> (evaluation_config_model, output_config_model)
EVALUATION_CONFIG_MODELS: dict[tuple[str, str], tuple[type[LLMJudgeConfig], type[BooleanOutputConfig]]] = {
    (EvaluationType.LLM_JUDGE.value, OutputType.BOOLEAN.value): (LLMJudgeConfig, BooleanOutputConfig),
}


def validate_evaluation_configs(
    evaluation_type: str, output_type: str, evaluation_config: dict, output_config: dict
) -> tuple[dict, dict]:
    """
    Validate evaluation_config and output_config based on evaluation_type + output_type combination.

    Returns tuple of (validated_evaluation_config, validated_output_config)
    """
    key = (evaluation_type, output_type)
    if key not in EVALUATION_CONFIG_MODELS:
        raise ValueError(f"Unsupported combination: {evaluation_type} + {output_type}")

    eval_model, output_model = EVALUATION_CONFIG_MODELS[key]

    try:
        validated_eval_config = eval_model(**evaluation_config)
        validated_output_config = output_model(**output_config)
        return validated_eval_config.model_dump(exclude_none=True), validated_output_config.model_dump(
            exclude_none=True
        )
    except Exception as e:
        raise ValueError(f"Invalid config for {evaluation_type}/{output_type}: {str(e)}") from e
