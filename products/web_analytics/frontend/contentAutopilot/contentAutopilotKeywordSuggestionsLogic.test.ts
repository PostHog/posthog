import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { aeoKeywordsCreate, aeoKeywordsSuggest, aeoKeywordsSuggestionRetrieve } from '../generated/api'
import type { AEOKeywordSuggestionJobApi } from '../generated/api.schemas'
import { contentAutopilotKeywordSuggestionsLogic } from './contentAutopilotKeywordSuggestionsLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    aeoKeywordsSuggest: jest.fn(),
    aeoKeywordsSuggestionRetrieve: jest.fn(),
    aeoKeywordsCreate: jest.fn(),
    aeoKeywordsList: jest.fn().mockResolvedValue([]),
    aeoKeywordsReport: jest.fn().mockResolvedValue(null),
    aeoKeywordsModifiers: jest.fn().mockResolvedValue(null),
}))

const JOB_ID = '00000000-0000-4000-8000-000000000902'
const pending: AEOKeywordSuggestionJobApi = { id: JOB_ID, status: 'pending', suggestions: [], error: '' }
const completed: AEOKeywordSuggestionJobApi = {
    ...pending,
    status: 'completed',
    suggestions: [
        { keyword: 'session replay', reason: 'Buyers search for it.', searches: 4 },
        { keyword: 'product analytics', reason: 'The category.', searches: 0 },
    ],
}

describe('contentAutopilotKeywordSuggestionsLogic', () => {
    let logic: ReturnType<typeof contentAutopilotKeywordSuggestionsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        // The job reference persists, so one test's job must not resume in the next.
        localStorage.clear()
        initKeaTests()
        jest.mocked(aeoKeywordsSuggest).mockResolvedValue(pending)
        jest.mocked(aeoKeywordsCreate).mockResolvedValue({ created: 1, skipped: 0 })
        logic = contentAutopilotKeywordSuggestionsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('polls a job until it completes, then adds only the selected keywords', async () => {
        logic.actions.openSuggest()
        logic.actions.setForm({ domain: 'https://example.com/pricing', count: 10 })
        await expectLogic(logic, () => logic.actions.startSuggestions()).toFinishAllListeners()

        expect(aeoKeywordsSuggest).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            domain: 'example.com',
            brand: '',
            description: '',
            count: 10,
        })
        expect(logic.values.job?.status).toBe('pending')

        jest.mocked(aeoKeywordsSuggestionRetrieve).mockResolvedValueOnce(completed)
        await expectLogic(logic, () => logic.actions.loadJob()).toFinishAllListeners()

        expect(logic.values.selectedKeywords).toEqual(['session replay', 'product analytics'])
        logic.actions.toggleSuggestion('product analytics')
        await expectLogic(logic, () => logic.actions.addSelected()).toFinishAllListeners()

        expect(aeoKeywordsCreate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            keywords: ['session replay'],
        })
        expect(logic.values).toMatchObject({ suggestOpen: false, job: null, jobRef: null, selectedKeywords: [] })
    })

    it('shows the API reason when a job cannot start', async () => {
        const { ApiError } = jest.requireActual('lib/api-error')
        jest.mocked(aeoKeywordsSuggest).mockRejectedValue(
            new ApiError('Bad request', 400, undefined, { detail: 'The keyword list is full.' })
        )
        logic.actions.setForm({ domain: 'example.com' })
        await expectLogic(logic, () => logic.actions.startSuggestions()).toFinishAllListeners()

        expect(logic.values).toMatchObject({ startError: 'The keyword list is full.', starting: false, job: null })
    })
})
