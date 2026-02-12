import json
from dataclasses import dataclass

import structlog
from bs4 import BeautifulSoup
from google.genai.types import Blob, Content, Part
from rest_framework import exceptions

from posthog.models.uploaded_media import UploadedMedia
from posthog.storage import object_storage

from ..llm import generate_structured_output
from ..prompts import TOUR_GENERATION_SYSTEM_PROMPT, TOUR_GENERATION_USER_PROMPT
from .constants import DEFAULT_MODEL
from .schema import TourGenerationResponse

logger = structlog.get_logger(__name__)


@dataclass
class ContentGenerationResult:
    tour_content: TourGenerationResponse
    trace_id: str
    index_to_step_id: dict[int, str]


def _get_element_context(step: dict) -> dict:
    if step.get("elementTargeting") == "auto":
        return {"inferred_text": step.get("inferenceData", {}).get("text")}
    elif step.get("elementTargeting") == "manual" and step.get("selector"):
        return {"selector": step.get("selector")}

    return {}


def _extract_content_text(step: dict) -> str | None:
    html = step.get("contentHtml", "")
    if not html:
        return None
    text = BeautifulSoup(html, "html.parser").get_text().strip()
    return text or None


def _effective_step_type(step: dict) -> str:
    if step.get("elementTargeting"):
        return "Element tooltip"
    return "Pop-up"


def _fetch_screenshot(media_id: str, team_id: int) -> tuple[bytes, str] | None:
    try:
        media = UploadedMedia.objects.get(id=media_id, team_id=team_id)
    except UploadedMedia.DoesNotExist:
        logger.warning("Screenshot media not found", media_id=media_id)
        return None

    if not media.media_location:
        return None

    image_bytes = object_storage.read_bytes(media.media_location, missing_ok=True)
    if not image_bytes:
        logger.warning("Screenshot bytes not found in storage", media_id=media_id)
        return None

    return image_bytes, media.content_type or "image/png"


def _fetch_step_screenshot(step: dict, step_index: int, team_id: int) -> list[Part]:
    media_id = step.get("screenshotMediaId")
    if not media_id:
        return []

    result = _fetch_screenshot(media_id, team_id)
    if not result:
        return []

    image_bytes, content_type = result
    return [
        Part(text=f"Screenshot for step {step_index}:"),
        Part(inline_data=Blob(data=image_bytes, mime_type=content_type)),
    ]


def generate_with_gemini(
    tour_id: str,
    title: str,
    goal: str,
    existing_steps: list[dict],
    team_id: int,
    distinct_id: str | None = None,
) -> ContentGenerationResult:
    if not existing_steps:
        raise exceptions.ValidationError("Elements cannot be empty")

    # build a index->ID mapping so we don't have to trust the LLM
    # not to hallucinate UUIDs
    index_to_step_id: dict[int, str] = {}

    clean_steps: list[dict] = []
    screenshot_parts: list[Part] = []

    def _is_valid_step(step: dict):
        return step.get("type") in ("element", "modal") and not step.get("survey")

    for idx, step in enumerate(step for step in existing_steps if _is_valid_step(step)):
        index_to_step_id[idx] = step["id"]
        clean_steps.append(
            {
                "step_id": idx,
                "type": _effective_step_type(step),
                "progression": step.get("progressionTrigger"),
                "existing_content": _extract_content_text(step),
                **_get_element_context(step),
            }
        )
        screenshot_parts.extend(_fetch_step_screenshot(step, idx, team_id))

    user_prompt = TOUR_GENERATION_USER_PROMPT.format(
        title=title,
        goal=goal,
        steps=json.dumps(clean_steps, indent=2),
        step_count=len(clean_steps),
    )
    contents = Content(parts=[Part(text=user_prompt), *screenshot_parts])

    tour_content, trace_id = generate_structured_output(
        model=DEFAULT_MODEL,
        system_prompt=TOUR_GENERATION_SYSTEM_PROMPT,
        contents=contents,
        response_schema=TourGenerationResponse,
        posthog_properties={
            "tour_id": tour_id,
            "ai_product": "tour_content_generation",
        },
        team_id=team_id,
        distinct_id=distinct_id,
    )

    return ContentGenerationResult(
        tour_content=tour_content,
        trace_id=trace_id,
        index_to_step_id=index_to_step_id,
    )
