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


@patch("products.surveys.backend.translation.generate_structured_output")
def test_generate_survey_translation_preserves_manual_choice_translations_after_choice_count_change(
    mock_generate_structured_output: Mock,
) -> None:
    mock_generate_structured_output.return_value = (
        SurveyTranslationResponse.model_validate(
            {
                "questions": [
                    {
                        "id": "question-1",
                        "choices": ["Analitica", "Encuestas", "Comentarios de clientes"],
                    }
                ]
            }
        ),
        "trace-2",
    )
    survey = {
        "name": "Customer feedback",
        "type": "popover",
        "questions": [
            {
                "id": "question-1",
                "question": "Why did you sign up?",
                "choices": ["Analytics", "Surveys", "Customer feedback"],
                "translations": {
                    "es": {
                        "choices": ["Manual analytics", "Surveys"],
                    }
                },
            }
        ],
    }

    _translations, questions, generated_paths, trace_id = generate_survey_translation(
        survey=survey,
        target_language="es",
        source_language="en",
        overwrite=False,
    )

    assert questions == [
        {
            "id": "question-1",
            "translations": {
                "es": {
                    "choices": ["Manual analytics", "Encuestas", "Comentarios de clientes"],
                }
            },
        }
    ]
    assert generated_paths == [
        "questions.0.translations.es.choices.1",
        "questions.0.translations.es.choices.2",
    ]
    assert trace_id == "trace-2"


@patch("products.surveys.backend.translation.generate_structured_output")
def test_generate_survey_translation_matches_questions_without_ids(mock_generate_structured_output: Mock) -> None:
    mock_generate_structured_output.return_value = (
        SurveyTranslationResponse.model_validate(
            {
                "questions": [
                    {"id": "__draft_question_0", "question": "Primera pregunta"},
                    {"id": "__draft_question_1", "question": "Segunda pregunta", "buttonText": "Enviar"},
                ]
            }
        ),
        "trace-2",
    )
    survey = {
        "name": "Draft survey",
        "questions": [
            {
                "type": "open",
                "question": "First question",
                "translations": {"es": {"question": "First question"}},
            },
            {
                "type": "open",
                "question": "Second question",
                "buttonText": "Submit",
                "translations": {"es": {"question": "Second question", "buttonText": "Submit"}},
            },
        ],
    }

    _translations, questions, generated_paths, trace_id = generate_survey_translation(
        survey=survey,
        target_language="es",
        overwrite=False,
    )

    assert questions == [
        {"id": "__draft_question_0", "translations": {"es": {"question": "Primera pregunta"}}},
        {"id": "__draft_question_1", "translations": {"es": {"question": "Segunda pregunta", "buttonText": "Enviar"}}},
    ]
    assert generated_paths == [
        "questions.0.translations.es.question",
        "questions.1.translations.es.question",
        "questions.1.translations.es.buttonText",
    ]
    assert trace_id == "trace-2"
    assert "__draft_question_1" in mock_generate_structured_output.call_args.kwargs["user_prompt"]
