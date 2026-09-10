from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Simplesat API docs (https://documenter.getpostman.com/view/457268/UVRDGRZ2).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "surveys": {
        "description": "A customer satisfaction survey (CSAT, CES, or NPS) configured in Simplesat.",
        "docs_url": "https://documenter.getpostman.com/view/457268/UVRDGRZ2",
        "columns": {
            "id": "The unique ID of the survey.",
            "name": "The survey name.",
            "brand_name": "The brand name shown to respondents.",
            "metric": "The metric the survey measures (e.g. CSAT, CES, NPS).",
            "survey_type": "The type of survey.",
            "survey_token": "The public token identifying the survey.",
        },
    },
    "questions": {
        "description": "A question belonging to a Simplesat survey.",
        "docs_url": "https://documenter.getpostman.com/view/457268/UVRDGRZ2",
        "columns": {
            "id": "The unique ID of the question.",
            "text": "The question text shown to respondents.",
            "metric": "The metric the question measures.",
            "order": "The display order of the question within the survey.",
            "choices": "The list of answer choices offered.",
            "rating_scale": "Whether the question uses a rating scale.",
            "required": "Whether an answer to the question is required.",
            "rules": "Conditional logic rules attached to the question.",
            "survey": "The survey this question belongs to.",
        },
    },
    "answers": {
        "description": "An individual answer submitted to a survey question.",
        "docs_url": "https://documenter.getpostman.com/view/457268/UVRDGRZ2",
        "columns": {
            "id": "The unique ID of the answer.",
            "choice": "The choice value selected by the respondent.",
            "choice_label": "The human-readable label of the selected choice.",
            "follow_up_answer": "The free-text follow-up comment, if any.",
            "sentiment": "The sentiment classification of the answer.",
            "published_as_testimonial": "Whether the answer has been published as a testimonial.",
            "response_id": "The ID of the response this answer is part of.",
            "question": "The question this answer responds to.",
            "survey": "The survey this answer belongs to.",
            "created": "When the answer was created.",
            "modified": "When the answer was last modified.",
        },
    },
    "responses": {
        "description": "A complete survey submission from a customer, grouping the individual answers.",
        "docs_url": "https://documenter.getpostman.com/view/457268/UVRDGRZ2",
        "columns": {
            "id": "The unique ID of the response.",
            "answers": "The individual answers included in this response.",
            "customer": "The customer who submitted the response.",
            "survey": "The survey that was answered.",
            "ticket": "The support ticket associated with the response, if any.",
            "ip_address": "The IP address the response was submitted from.",
            "created": "When the response was created.",
            "modified": "When the response was last modified.",
        },
    },
}
