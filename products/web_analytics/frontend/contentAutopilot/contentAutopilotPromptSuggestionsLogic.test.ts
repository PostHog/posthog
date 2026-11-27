import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    aeoBrandsCreate,
    aeoPromptsBulkImport,
    aeoPromptsSuggest,
    aeoPromptsSuggestionRetrieve,
    aeoSetupContext,
} from '../generated/api'
import type {
    AEOBrandApi,
    AEOPromptSuggestionApi,
    AEOPromptSuggestionJobApi,
    AEOSetupContextApi,
} from '../generated/api.schemas'
import { contentAutopilotPromptSuggestionsLogic, siteDomain } from './contentAutopilotPromptSuggestionsLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    aeoPromptsSuggest: jest.fn(),
    aeoPromptsSuggestionRetrieve: jest.fn(),
    aeoPromptsBulkImport: jest.fn(),
    aeoBrandsCreate: jest.fn(),
    aeoSetupContext: jest.fn(),
}))

const suggestion = (prompt: string, topic: string): AEOPromptSuggestionApi => ({
    prompt,
    topic,
    circle: 'battleground',
    funnel_stage: 'bottom',
    branded: false,
    reason: 'Buyers compare tools.',
})

const JOB_ID = '00000000-0000-4000-8000-000000000901'
const pending: AEOPromptSuggestionJobApi = {
    id: JOB_ID,
    status: 'pending',
    suggestions: [],
    competitors: [],
    error: '',
}
const completed: AEOPromptSuggestionJobApi = {
    ...pending,
    status: 'completed',
    suggestions: [
        suggestion('Best session replay tool?', 'Replay'),
        suggestion('Cheapest analytics tool?', 'Analytics'),
    ],
}

describe('contentAutopilotPromptSuggestionsLogic', () => {
    let logic: ReturnType<typeof contentAutopilotPromptSuggestionsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        // The job reference persists, so one test's job must not resume in the next.
        localStorage.clear()
        initKeaTests()
        jest.mocked(aeoPromptsSuggest).mockResolvedValue(pending)
        jest.mocked(aeoPromptsBulkImport).mockResolvedValue({ created: 1, updated: 0, skipped: 0 })
        jest.mocked(aeoBrandsCreate).mockResolvedValue({} as AEOBrandApi)
        jest.mocked(aeoSetupContext).mockResolvedValue({
            own_domains: ['example.com'],
            engines: [],
            websites: [],
        } as unknown as AEOSetupContextApi)
        logic = contentAutopilotPromptSuggestionsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('polls a job until it completes, then imports only the selected suggestions', async () => {
        logic.actions.openSuggest()
        logic.actions.setForm({ domain: 'https://example.com/pricing' })
        await expectLogic(logic, () => logic.actions.startSuggestions()).toFinishAllListeners()

        expect(aeoPromptsSuggest).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ domain: 'example.com', count: 20 })
        )
        expect(logic.values.job?.status).toBe('pending')

        // A poll that still finds the job running leaves it pending.
        jest.mocked(aeoPromptsSuggestionRetrieve).mockResolvedValueOnce(pending).mockResolvedValueOnce(completed)
        await expectLogic(logic, () => logic.actions.loadJob()).toFinishAllListeners()
        expect(logic.values.job?.status).toBe('pending')
        await expectLogic(logic, () => logic.actions.loadJob()).toFinishAllListeners()

        expect(logic.values.selectedPrompts).toEqual(['Best session replay tool?', 'Cheapest analytics tool?'])
        logic.actions.toggleSuggestion('Cheapest analytics tool?')
        await expectLogic(logic, () => logic.actions.addSelected()).toFinishAllListeners()

        expect(aeoPromptsBulkImport).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            prompts: [{ prompt: 'Best session replay tool?', topic: 'Replay', origin: 'suggestion' }],
        })
        expect(logic.values).toMatchObject({ suggestOpen: false, job: null, adding: false, selectedPrompts: [] })

        // A second run starts with all of its suggestions selected, not the previous run's choices.
        jest.mocked(aeoPromptsSuggestionRetrieve).mockResolvedValueOnce(completed)
        await expectLogic(logic, () => logic.actions.startSuggestions()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadJob()).toFinishAllListeners()
        expect(logic.values.selectedSuggestions).toHaveLength(2)
    })

    it('resumes a job after the page unmounts and ignores a poll that would overlap another', async () => {
        logic.actions.setForm({ domain: 'example.com' })
        await expectLogic(logic, () => logic.actions.startSuggestions()).toFinishAllListeners()
        logic.unmount()

        let finishPoll: (job: AEOPromptSuggestionJobApi) => void = () => {}
        jest.mocked(aeoPromptsSuggestionRetrieve).mockReturnValueOnce(
            new Promise((resolve) => {
                finishPoll = resolve
            })
        )
        logic = contentAutopilotPromptSuggestionsLogic()
        logic.mount()
        // The remount polls the stored job; a second poll while it runs sends no request.
        logic.actions.loadJob()
        expect(aeoPromptsSuggestionRetrieve).toHaveBeenCalledTimes(1)

        finishPoll(completed)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.job?.status).toBe('completed')
        expect(logic.values.selectedPrompts).toHaveLength(2)
    })

    it('shows the API reason when a job cannot start', async () => {
        const { ApiError } = jest.requireActual('lib/api-error')
        jest.mocked(aeoPromptsSuggest).mockRejectedValue(
            new ApiError('Forbidden', 403, undefined, {
                detail: 'Prompt suggestions need AI data processing approved.',
            })
        )
        logic.actions.setForm({ domain: 'example.com' })
        await expectLogic(logic, () => logic.actions.startSuggestions()).toFinishAllListeners()

        expect(logic.values).toMatchObject({
            job: null,
            starting: false,
            startError: 'Prompt suggestions need AI data processing approved.',
        })
    })

    it.each([
        ['example.com', 'example.com'],
        ['https://example.com/pricing?utm=x#plans', 'example.com'],
        ['Example.com:8080', 'example.com'],
        ['example.com.', 'example.com'],
        ['  ', ''],
    ])('reads the site from %p', (input, expected) => {
        expect(siteDomain(input)).toBe(expected)
    })

    it('saves the site as your brand and the kept competitors when it adds the prompts', async () => {
        jest.mocked(aeoSetupContext).mockResolvedValue({
            own_domains: [],
            engines: [],
            websites: [],
        } as unknown as AEOSetupContextApi)
        logic.unmount()
        logic = contentAutopilotPromptSuggestionsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setForm({ domain: 'https://www.example.com/', brand: 'Example' })
        await expectLogic(logic, () => logic.actions.startSuggestions()).toFinishAllListeners()
        jest.mocked(aeoPromptsSuggestionRetrieve).mockResolvedValueOnce({
            ...completed,
            competitors: [
                { name: 'Rival', domain: 'rival.example.org' },
                { name: 'Dropped', domain: 'dropped.example.org' },
                { name: 'Only a name', domain: '' },
            ],
        })
        await expectLogic(logic, () => logic.actions.loadJob()).toFinishAllListeners()
        expect(logic.values.selectedCompetitors).toEqual(['rival.example.org', 'dropped.example.org'])

        logic.actions.toggleCompetitor('dropped.example.org')
        await expectLogic(logic, () => logic.actions.addSelected()).toFinishAllListeners()

        const team = String(MOCK_DEFAULT_TEAM.id)
        expect(jest.mocked(aeoBrandsCreate).mock.calls.map(([, body]) => body)).toEqual([
            { domain: 'example.com', kind: 'own', name: 'Example' },
            { domain: 'rival.example.org', kind: 'competitor' },
        ])
        expect(aeoBrandsCreate).toHaveBeenCalledWith(team, expect.anything())
    })
})
