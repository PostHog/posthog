import { Survey, SurveyQuestion, SurveyQuestionType } from 'posthog-js'

export type FeedbackAnswer = string | string[]

export function supportsFeedbackSurvey(survey: Survey): boolean {
    const first = survey.questions[0]
    return (
        survey.questions.length >= 2 &&
        survey.questions.length <= 5 &&
        first.type === SurveyQuestionType.Rating &&
        first.scale === 2 &&
        first.display === 'emoji' &&
        new Set(survey.questions.map(({ id }) => id)).size === survey.questions.length &&
        survey.questions.every(
            (question) =>
                !!question.id &&
                !question.branching &&
                !question.validation?.length &&
                (question.type === SurveyQuestionType.Open ||
                    question.type === SurveyQuestionType.Rating ||
                    ((question.type === SurveyQuestionType.SingleChoice ||
                        question.type === SurveyQuestionType.MultipleChoice) &&
                        question.choices.length > 0 &&
                        !question.hasOpenChoice &&
                        !question.shuffleOptions))
        )
    )
}

export function isFeedbackAnswerValid(question: SurveyQuestion, answer?: FeedbackAnswer): boolean {
    if (answer === undefined || answer === '' || (Array.isArray(answer) && !answer.length)) {
        return !!question.optional
    }
    switch (question.type) {
        case SurveyQuestionType.Open:
            return typeof answer === 'string' && answer.length <= 2000 && (!!question.optional || !!answer.trim())
        case SurveyQuestionType.SingleChoice:
            return typeof answer === 'string' && question.choices.includes(answer)
        case SurveyQuestionType.MultipleChoice:
            return Array.isArray(answer) && answer.every((choice) => question.choices.includes(choice))
        case SurveyQuestionType.Rating:
            return typeof answer === 'string' && ratingValues(question.scale).includes(answer)
        default:
            return false
    }
}

export function ratingValues(scale: number): string[] {
    const start = scale === 10 ? 0 : 1
    return Array.from({ length: scale - start + 1 }, (_, index) => String(start + index))
}
