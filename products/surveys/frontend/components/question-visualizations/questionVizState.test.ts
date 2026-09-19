import { ChoiceQuestionProcessedResponses, SurveyQuestionType } from '~/types'

import { resolveQuestionVizState } from './questionVizState'

const QUESTION_ID = 'q1'

const ANSWERED: ChoiceQuestionProcessedResponses = {
    type: SurveyQuestionType.Rating,
    data: [{ label: '5', value: 2, isPredefined: true }],
    totalResponses: 2,
    noResponseCount: 1,
}

const SKIPPED_ONLY: ChoiceQuestionProcessedResponses = {
    type: SurveyQuestionType.Rating,
    data: [],
    totalResponses: 0,
    noResponseCount: 3,
}

describe('resolveQuestionVizState', () => {
    it('reports no responses for a question that is absent from loaded results', () => {
        expect(
            resolveQuestionVizState({ responsesByQuestion: {}, questionId: QUESTION_ID, isRefreshingResults: false })
        ).toEqual({ kind: 'empty', noResponseCount: 0 })
    })

    it('keeps the skipped count when the question was loaded with no answers', () => {
        expect(
            resolveQuestionVizState({
                responsesByQuestion: { [QUESTION_ID]: SKIPPED_ONLY },
                questionId: QUESTION_ID,
                isRefreshingResults: false,
            })
        ).toEqual({ kind: 'empty', noResponseCount: 3 })
    })

    it.each([
        ['the results have not arrived yet', undefined, false],
        ['a refresh is in flight', {}, true],
    ])('waits when %s', (_description, responsesByQuestion, isRefreshingResults) => {
        expect(resolveQuestionVizState({ responsesByQuestion, questionId: QUESTION_ID, isRefreshingResults })).toEqual({
            kind: 'loading',
        })
    })

    it('keeps showing answers while a refresh is in flight', () => {
        expect(
            resolveQuestionVizState({
                responsesByQuestion: { [QUESTION_ID]: ANSWERED },
                questionId: QUESTION_ID,
                isRefreshingResults: true,
            })
        ).toEqual({ kind: 'content', processedData: ANSWERED })
    })
})
