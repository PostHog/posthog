import { QuestionProcessedResponses, ResponsesByQuestion } from '~/types'

export type QuestionVizState =
    | { kind: 'loading' }
    | { kind: 'empty'; noResponseCount: number }
    | { kind: 'content'; processedData: QuestionProcessedResponses }

interface Params {
    responsesByQuestion: ResponsesByQuestion | undefined
    questionId: string
    isRefreshingResults: boolean
}

/**
 * Which of the three screens a question renders.
 *
 * A question nobody answered contributes no rows to the results query, so it is absent from
 * `responsesByQuestion` rather than present with a zero count. Absent means "no responses" once
 * the results have arrived, and only means "loading" before that.
 */
export function resolveQuestionVizState({
    responsesByQuestion,
    questionId,
    isRefreshingResults,
}: Params): QuestionVizState {
    const processedData = responsesByQuestion?.[questionId]

    if (processedData && processedData.totalResponses > 0 && processedData.data.length > 0) {
        return { kind: 'content', processedData }
    }

    if (isRefreshingResults || !responsesByQuestion) {
        return { kind: 'loading' }
    }

    return {
        kind: 'empty',
        noResponseCount: processedData && 'noResponseCount' in processedData ? processedData.noResponseCount : 0,
    }
}
