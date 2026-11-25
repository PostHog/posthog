import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import {
    aeoPromptsBulkImport,
    aeoPromptsList,
    aeoPromptsPartialUpdate,
    aeoPromptsTopics,
    aeoSetupContext,
} from '../generated/api'
import type { AEOPromptApi, AEOSetupContextApi } from '../generated/api.schemas'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'
import { PROMPTS_PAGE_SIZE, contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { EXAMPLE_PROMPT_TOPICS, EXAMPLE_PROMPTS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    aeoPromptsList: jest.fn(),
    aeoPromptsTopics: jest.fn(),
    aeoPromptsPartialUpdate: jest.fn(),
    aeoPromptsBulkImport: jest.fn(),
    aeoSetupContext: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({ lemonToast: { error: jest.fn(), success: jest.fn() } }))

const mockPromptsList = jest.mocked(aeoPromptsList)
const mockPromptsTopics = jest.mocked(aeoPromptsTopics)
const mockPromptsPartialUpdate = jest.mocked(aeoPromptsPartialUpdate)
const mockPromptsBulkImport = jest.mocked(aeoPromptsBulkImport)
const mockSetupContext = jest.mocked(aeoSetupContext)

const setupContext = (activePrompts: number, maxActivePrompts: number): AEOSetupContextApi => ({
    websites: [],
    own_domains: ['hedgebox.net'],
    active_prompts: activePrompts,
    max_active_prompts: maxActivePrompts,
    paused_prompts: 0,
    keywords: 0,
    has_checks: true,
    ai_data_processing_approved: true,
    first_run_available: true,
    prompt_target: 20,
    website_days: 7,
    engines: [],
})

describe('contentAutopilotPromptsLogic', () => {
    let logic: ReturnType<typeof contentAutopilotPromptsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        // The branded segment persists in local storage, so a choice made in one test must not leak into the next.
        localStorage.clear()
        initKeaTests()
        mockPromptsList.mockResolvedValue({ count: 120, next: null, previous: null, results: EXAMPLE_PROMPTS })
        mockPromptsTopics.mockResolvedValue(EXAMPLE_PROMPT_TOPICS)
        mockSetupContext.mockResolvedValue(setupContext(3, 100))
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('resets to the first page and sends the filters when a shared filter, archived or needs improvement changes', async () => {
        logic = contentAutopilotPromptsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const filters = contentAutopilotFiltersLogic

        logic.actions.setPromptsPage(3)
        await expectLogic(logic).toFinishAllListeners()
        expect(mockPromptsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: PROMPTS_PAGE_SIZE,
            offset: 2 * PROMPTS_PAGE_SIZE,
            topic: undefined,
            branded: false,
        })

        filters.actions.setTopic('', 'prompts')
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ promptsPage: 1 })
        expect(mockPromptsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: PROMPTS_PAGE_SIZE,
            offset: 0,
            topic: '',
            branded: false,
        })

        logic.actions.setPromptsPage(2)
        logic.actions.setShowArchived(true)
        filters.actions.setBrandedSegment('all', 'prompts')
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ promptsPage: 1 })
        expect(mockPromptsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: PROMPTS_PAGE_SIZE,
            offset: 0,
            topic: '',
            include_archived: true,
            branded: undefined,
        })

        // The date range and the engine only narrow the needs improvement view.
        filters.actions.setDates('-7d', null, 'prompts')
        filters.actions.setEngine('exa-answer', 'prompts')
        await expectLogic(logic).toFinishAllListeners()
        expect(mockPromptsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: PROMPTS_PAGE_SIZE,
            offset: 0,
            topic: '',
            include_archived: true,
            branded: undefined,
        })

        logic.actions.setPromptsPage(2)
        logic.actions.setNeedsImprovement(true)
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ promptsPage: 1, promptEngines: ['exa-answer'] })
        expect(mockPromptsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: PROMPTS_PAGE_SIZE,
            offset: 0,
            topic: '',
            include_archived: true,
            branded: undefined,
            needs_improvement: true,
            date_from: '-7d',
            engine: 'exa-answer',
        })
    })

    it.each([
        ['forbidden', new ApiError('This feature is not available.', 403)],
        ['failed', new ApiError('Server error', 500)],
    ])('reports a %s error when the prompts fail to load', async (expected, error) => {
        mockPromptsList.mockRejectedValue(error)
        silenceKeaLoadersErrors()
        try {
            logic = contentAutopilotPromptsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ promptsError: expected, prompts: null })
        } finally {
            resumeKeaLoadersErrors()
        }
    })

    it('drops a stale prompts failure after a newer request resolved', async () => {
        const settlers: { resolve: () => void; reject: () => void }[] = []
        mockPromptsList.mockImplementation(
            () =>
                new Promise((resolve, reject) => {
                    settlers.push({
                        resolve: () => resolve({ count: 1, next: null, previous: null, results: [EXAMPLE_PROMPTS[0]] }),
                        reject: () => reject(new ApiError('Server error', 500)),
                    })
                })
        )
        logic = contentAutopilotPromptsLogic()
        logic.mount()
        contentAutopilotFiltersLogic.actions.setTopic('pricing', 'prompts')
        await expectLogic(logic).toDispatchActions(['loadAeoPrompts', 'loadAeoPrompts'])
        expect(settlers).toHaveLength(2)

        settlers[1].resolve()
        await expectLogic(logic).toDispatchActions(['loadAeoPromptsSuccess'])
        settlers[0].reject()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toNotHaveDispatchedActions(['loadAeoPromptsFailure'])
            .toMatchValues({ promptsError: null, prompts: expect.objectContaining({ count: 1 }) })
    })

    it.each([
        ['saves', true, false],
        ['rolls back', false, true],
    ])('turns a prompt off optimistically, then %s', async (_name, succeeds, expectedActive) => {
        const prompt = EXAMPLE_PROMPTS[0]
        let settle: () => void = () => {}
        mockPromptsPartialUpdate.mockReturnValue(
            new Promise<AEOPromptApi>((resolve, reject) => {
                settle = () => (succeeds ? resolve({ ...prompt, active: false }) : reject(new Error('Server error')))
            })
        )
        logic = contentAutopilotPromptsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setPromptActive(prompt.id, false)
        expect(logic.values.prompts?.results[0].active).toBe(false)
        expect(logic.values.promptActiveUpdating).toEqual({ [prompt.id]: true })

        settle()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockPromptsPartialUpdate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), prompt.id, {
            active: false,
        })
        expect(logic.values.prompts?.results[0].active).toBe(expectedActive)
        expect(logic.values.promptActiveUpdating).toEqual({})
        expect(lemonToast.error).toHaveBeenCalledTimes(succeeds ? 0 : 1)
    })

    it.each([
        ['closes the dialog and reloads the list', true],
        ['keeps the dialog open and shows why', false],
    ])('sends one prompt per unique line, then %s', async (_name, succeeds) => {
        if (succeeds) {
            mockPromptsBulkImport.mockResolvedValue({ created: 2, updated: 0, skipped: 0 })
        } else {
            mockPromptsBulkImport.mockRejectedValue(
                new ApiError('Bad request', 400, undefined, { detail: 'Prompt is too long' })
            )
        }
        logic = contentAutopilotPromptsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        mockPromptsList.mockClear()

        logic.actions.openAddPrompts()
        logic.actions.addPrompts(
            '  Best session replay tool?\n\nbest session replay tool?\nHow do I track signups?  ',
            ' Replay '
        )
        await expectLogic(logic).toFinishAllListeners()

        expect(mockPromptsBulkImport).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            prompts: [
                { prompt: 'Best session replay tool?', topic: 'Replay' },
                { prompt: 'How do I track signups?', topic: 'Replay' },
            ],
        })
        expect(logic.values).toMatchObject({ addPromptsOpen: !succeeds, addPromptsSubmitting: false })
        expect(mockPromptsList).toHaveBeenCalledTimes(succeeds ? 1 : 0)
        expect(jest.mocked(lemonToast.error).mock.calls.map(([message]) => message)).toEqual(
            succeeds ? [] : ['Prompt is too long']
        )
    })

    it('reads the prompt limit, shows why a refused toggle failed, and reloads the count after a change', async () => {
        const prompt = EXAMPLE_PROMPTS.find((example) => !example.active) as AEOPromptApi
        const activeOf = (): boolean | undefined =>
            logic.values.prompts?.results.find((row) => row.id === prompt.id)?.active
        mockSetupContext.mockResolvedValue(setupContext(100, 100))
        logic = contentAutopilotPromptsLogic()
        logic.mount()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ setupContext: setupContext(100, 100), promptLimitReached: true })

        const limitMessage =
            "You're tracking 100 prompts, and this project can track up to 100. Turn off some prompts first."
        mockPromptsPartialUpdate.mockRejectedValueOnce(
            new ApiError('Bad request', 400, undefined, { detail: limitMessage })
        )
        logic.actions.setPromptActive(prompt.id, true)
        await expectLogic(logic).toFinishAllListeners()
        expect(activeOf()).toBe(false)
        expect(lemonToast.error).toHaveBeenCalledWith(limitMessage)

        mockSetupContext.mockResolvedValue(setupContext(101, 150))
        mockPromptsPartialUpdate.mockResolvedValueOnce({ ...prompt, active: true })
        logic.actions.setPromptActive(prompt.id, true)
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ setupContext: setupContext(101, 150), promptLimitReached: false })
        expect(activeOf()).toBe(true)
    })
})
