from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from products.surveys.backend.llm import generate_structured_output

DEFAULT_TRANSLATION_MODEL = "gemini-3.1-flash-lite-preview"
DRAFT_TRANSLATION_QUESTION_ID_PREFIX = "__draft_question_"


class SurveyRootTranslation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    thankYouMessageHeader: str | None = None
    thankYouMessageDescription: str | None = None
    thankYouMessageCloseButtonText: str | None = None


class SurveyQuestionTranslation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    question: str | None = None
    description: str | None = None
    buttonText: str | None = None
    choices: list[str] | None = None
    lowerBoundLabel: str | None = None
    upperBoundLabel: str | None = None
    link: str | None = None


class SurveyTranslationResponse(BaseModel):
    root: SurveyRootTranslation = Field(default_factory=SurveyRootTranslation)
    questions: list[SurveyQuestionTranslation] = Field(default_factory=list)


SYSTEM_PROMPT = """You translate PostHog survey copy.

Return JSON that matches the requested schema.
Rules:
- Translate only user-facing copy.
- Preserve question ids exactly.
- Preserve choice order and choice count exactly.
- Keep empty source strings empty or omitted.
- Do not invent missing fields.
- Keep URLs unchanged unless the source URL itself is localized.
- Preserve placeholders and product names."""


def _root_source(survey: dict[str, Any]) -> dict[str, Any]:
    appearance = survey.get("appearance") or {}
    return {
        "name": survey.get("name"),
        "description_or_goal": survey.get("description"),
        "type": survey.get("type"),
        "thankYouMessageHeader": appearance.get("thankYouMessageHeader"),
        "thankYouMessageDescription": appearance.get("thankYouMessageDescription"),
        "thankYouMessageCloseButtonText": appearance.get("thankYouMessageCloseButtonText"),
        "translations": survey.get("translations") or {},
    }


def _questions_source(survey: dict[str, Any]) -> list[dict[str, Any]]:
    questions = survey.get("questions")
    if not isinstance(questions, list):
        return []

    source_questions: list[dict[str, Any]] = []
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue

        source_questions.append(
            {
                **question,
                "id": question.get("id") or f"{DRAFT_TRANSLATION_QUESTION_ID_PREFIX}{index}",
            }
        )

    return source_questions


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _should_replace(existing_value: Any, source_value: Any, overwrite: bool) -> bool:
    return overwrite or _is_missing(existing_value) or existing_value == source_value


def _filter_existing_fields(
    *,
    target_language: str,
    source: dict[str, Any],
    result: SurveyTranslationResponse,
    overwrite: bool,
) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]], list[str]]:
    root_source = _root_source(source)
    root_existing = root_source.get("translations", {}).get(target_language, {})
    root_result = result.root.model_dump(exclude_none=True)
    root_translation: dict[str, str] = {}
    generated_paths: list[str] = []

    for field, value in root_result.items():
        if value != "" and _should_replace(root_existing.get(field), root_source.get(field), overwrite):
            root_translation[field] = value
            generated_paths.append(f"translations.{target_language}.{field}")

    questions_by_id = {
        str(question.get("id")): (index, question) for index, question in enumerate(_questions_source(source))
    }
    question_patches: list[dict[str, Any]] = []

    for translated_question in result.questions:
        match = questions_by_id.get(translated_question.id)
        if not match:
            continue

        question_index, question = match
        existing_translation = (question.get("translations") or {}).get(target_language, {})
        question_translation: dict[str, Any] = {}
        translated_values = translated_question.model_dump(exclude={"id"}, exclude_none=True)

        for field, value in translated_values.items():
            if field == "choices":
                source_choices = question.get("choices")
                if (
                    not isinstance(source_choices, list)
                    or not isinstance(value, list)
                    or len(value) != len(source_choices)
                ):
                    continue
                existing_choices = existing_translation.get("choices")
                if overwrite or not isinstance(existing_choices, list):
                    question_translation[field] = value
                    generated_paths.extend(
                        f"questions.{question_index}.translations.{target_language}.choices.{choice_index}"
                        for choice_index in range(len(value))
                    )
                    continue

                choices = list(value) if len(existing_choices) != len(source_choices) else list(existing_choices)
                choice_paths = []
                for choice_index, translated_choice in enumerate(value):
                    if choice_index >= len(existing_choices):
                        choice_paths.append(
                            f"questions.{question_index}.translations.{target_language}.choices.{choice_index}"
                        )
                        continue

                    if _should_replace(existing_choices[choice_index], source_choices[choice_index], overwrite):
                        choices[choice_index] = translated_choice
                        choice_paths.append(
                            f"questions.{question_index}.translations.{target_language}.choices.{choice_index}"
                        )
                    else:
                        choices[choice_index] = existing_choices[choice_index]

                if choice_paths:
                    question_translation[field] = choices
                    generated_paths.extend(choice_paths)
                elif len(existing_choices) != len(choices):
                    question_translation[field] = choices
                continue

            if value != "" and _should_replace(existing_translation.get(field), question.get(field), overwrite):
                question_translation[field] = value
                generated_paths.append(f"questions.{question_index}.translations.{target_language}.{field}")

        if question_translation:
            question_patches.append(
                {"id": translated_question.id, "translations": {target_language: question_translation}}
            )

    return ({target_language: root_translation} if root_translation else {}, question_patches, generated_paths)


def generate_survey_translation(
    *,
    survey: dict[str, Any],
    target_language: str,
    source_language: str = "en",
    overwrite: bool = False,
    model: str = DEFAULT_TRANSLATION_MODEL,
    distinct_id: str | None = None,
    team_id: int | None = None,
) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]], list[str], str]:
    root = _root_source(survey)
    questions = _questions_source(survey)
    result, trace_id = generate_structured_output(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=(
            f"Translate this survey from {source_language} to {target_language}.\n"
            f"Survey root: {root}\n"
            f"Questions: {questions}"
        ),
        response_schema=SurveyTranslationResponse,
        posthog_properties={"ai_product": "survey_translation", "target_language": target_language},
        team_id=team_id,
        distinct_id=distinct_id,
    )

    translations, question_patches, generated_paths = _filter_existing_fields(
        target_language=target_language,
        source=survey,
        result=result,
        overwrite=overwrite,
    )
    return translations, question_patches, generated_paths, trace_id
