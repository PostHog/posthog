from unittest.mock import Mock, patch

from products.surveys.backend.translation import SurveyTranslationResponse, generate_survey_translation


@patch("products.surveys.backend.translation.generate_structured_output")
def test_generate_survey_translation_preserves_manual_translations(mock_generate_structured_output: Mock) -> None:
    mock_generate_structured_output.return_value = (
        SurveyTranslationResponse.model_validate(
            {
                "root": {
                    "name": "Comentarios de clientes",
                    "thankYouMessageHeader": "Gracias",
                },
                "questions": [
                    {
                        "id": "question-1",
                        "question": "Por que te registraste?",
                        "choices": ["Analitica", "Encuestas"],
                    }
                ],
            }
        ),
        "trace-1",
    )
    survey = {
        "name": "Customer feedback",
        "description": "Learn why users sign up so onboarding can improve.",
        "type": "popover",
        "appearance": {"thankYouMessageHeader": "Thanks"},
        "translations": {"es": {"name": "Manual title", "thankYouMessageHeader": "Thanks"}},
        "questions": [
            {
                "id": "question-1",
                "question": "Why did you sign up?",
                "choices": ["Analytics", "Surveys"],
                "translations": {
                    "es": {
                        "question": "Why did you sign up?",
                        "choices": ["Manual analytics", "Surveys"],
                    }
                },
            }
        ],
    }

    translations, questions, generated_paths, trace_id = generate_survey_translation(
        survey=survey,
        target_language="es",
        source_language="en",
        overwrite=False,
        distinct_id="user-1",
        team_id=1,
    )

    assert translations == {"es": {"thankYouMessageHeader": "Gracias"}}
    assert questions == [
        {
            "id": "question-1",
            "translations": {
                "es": {
                    "question": "Por que te registraste?",
                    "choices": ["Manual analytics", "Encuestas"],
                }
            },
        }
    ]
    assert generated_paths == [
        "translations.es.thankYouMessageHeader",
        "questions.0.translations.es.question",
        "questions.0.translations.es.choices.1",
    ]
    assert trace_id == "trace-1"
    assert "description_or_goal" in mock_generate_structured_output.call_args.kwargs["user_prompt"]
