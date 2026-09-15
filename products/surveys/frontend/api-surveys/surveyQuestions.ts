import { Survey, SurveyQuestion, SurveyQuestionType } from 'posthog-js'

export type SurveyAnswer = string | string[]

export function ratingValues(scale: number): string[] {
    const start = scale === 10 ? 0 : 1
    return Array.from({ length: scale - start + 1 }, (_, index) => String(start + index))
}

export function supportsApiSurvey(survey: Survey): boolean {
    return (
        survey.questions.length > 0 &&
        new Set(survey.questions.map(({ id }) => id)).size === survey.questions.length &&
        survey.questions.every(
            (question) =>
                !!question.id &&
                !question.branching &&
                !question.validation?.length &&
                (question.type === SurveyQuestionType.Open ||
                    (question.type === SurveyQuestionType.Rating &&
                        (question.display === 'number' || (question.display === 'emoji' && question.scale === 2))) ||
                    ((question.type === SurveyQuestionType.SingleChoice ||
                        question.type === SurveyQuestionType.MultipleChoice) &&
                        question.choices.length > 0 &&
                        new Set(question.choices).size === question.choices.length &&
                        !question.hasOpenChoice &&
                        !question.shuffleOptions))
        )
    )
}

export function isSurveyAnswerValid(question: SurveyQuestion, answer?: SurveyAnswer): boolean {
    if (answer === undefined || answer === '' || (Array.isArray(answer) && !answer.length)) {
        return !!question.optional
    }
    switch (question.type) {
        case SurveyQuestionType.Open:
            return typeof answer === 'string' && answer.length <= 2000 && (!!question.optional || !!answer.trim())
        case SurveyQuestionType.SingleChoice:
            return typeof answer === 'string' && question.choices.includes(answer)
        case SurveyQuestionType.MultipleChoice:
            return (
                Array.isArray(answer) &&
                new Set(answer).size === answer.length &&
                answer.every((choice) => question.choices.includes(choice))
            )
        case SurveyQuestionType.Rating:
            return typeof answer === 'string' && ratingValues(question.scale).includes(answer)
        default:
            return false
    }
}
