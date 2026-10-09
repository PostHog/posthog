import type {
    LogsNaturalLanguageQueryResponseApi,
    _LogsNaturalLanguageCandidateApi,
} from 'products/logs/frontend/generated/api.schemas'

import { looksLikeNaturalLanguage, shouldAutoApply } from './naturalLanguageSearch'

const candidate: _LogsNaturalLanguageCandidateApi = {
    label: 'Errors in the last 2 hours',
    query: { dateRange: { date_from: '-2h' }, severityLevels: ['error'], serviceNames: [], filterGroup: [] },
    probability: null,
}

function response(overrides: Partial<LogsNaturalLanguageQueryResponseApi>): LogsNaturalLanguageQueryResponseApi {
    return {
        candidates: [candidate, candidate],
        confidence: null,
        ranked_by: 'proposal_order',
        dropped_count: 0,
        ...overrides,
    }
}

describe('naturalLanguageSearch', () => {
    test.each([
        ['one candidate', response({ candidates: [candidate] }), true],
        ['confident decision model', response({ ranked_by: 'decision_model', confidence: 0.85 }), true],
        ['unsure decision model', response({ ranked_by: 'decision_model', confidence: 0.5 }), false],
        ['several candidates nobody ranked', response({ ranked_by: 'proposal_order', confidence: null }), false],
        ['no candidates', response({ candidates: [] }), false],
    ])('shouldAutoApply with %s', (_name, input, expected) => {
        expect(shouldAutoApply(input)).toBe(expected)
    })

    test.each([
        ['show me error logs in the last 2 hours', true],
        ['  timeout  error ', false],
        ['checkout', false],
    ])('looksLikeNaturalLanguage(%p)', (query, expected) => {
        expect(looksLikeNaturalLanguage(query)).toBe(expected)
    })
})
