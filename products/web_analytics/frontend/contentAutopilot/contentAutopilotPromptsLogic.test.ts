import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { aeoPromptsBulkImport, aeoPromptsList, aeoPromptsPartialUpdate, aeoPromptsTopics } from '../generated/api'
import type { AEOPromptApi } from '../generated/api.schemas'
import { PROMPTS_PAGE_SIZE, contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { EXAMPLE_PROMPT_TOPICS, EXAMPLE_PROMPTS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    aeoPromptsList: jest.fn(),
    aeoPromptsTopics: jest.fn(),
    aeoPromptsPartialUpdate: jest.fn(),
    aeoPromptsBulkImport: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({ lemonToast: { error: jest.fn(), success: jest.fn() } }))

const mockPromptsList = jest.mocked(aeoPromptsList)
const mockPromptsTopics = jest.mocked(aeoPromptsTopics)
const mockPromptsPartialUpdate = jest.mocked(aeoPromptsPartialUpdate)
const mockPromptsBulkImport = jest.mocked(aeoPromptsBulkImport)

describe('contentAutopilotPromptsLogic', () => {
    let logic: ReturnType<typeof contentAutopilotPromptsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        mockPromptsList.mockResolvedValue({ count: 120, next: null, previous: null, results: EXAMPLE_PROMPTS })
        mockPromptsTopics.mockResolvedValue(EXAMPLE_PROMPT_TOPICS)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('resets to the first page and sends the filters when the topic, archived, needs improvement or branded filter changes', async () => {
        logic = contentAutopilotPromptsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setPromptsPage(3)
        await expectLogic(logic).toFinishAllListeners()
        expect(mockPromptsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: PROMPTS_PAGE_SIZE,
            offset: 2 * PROMPTS_PAGE_SIZE,
            topic: undefined,
        })

        logic.actions.setPromptsTopic('')
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ promptsPage: 1 })
        expect(mockPromptsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: PROMPTS_PAGE_SIZE,
            offset: 0,
            topic: '',
        })

        logic.actions.setPromptsPage(2)
        logic.actions.setShowArchived(true)
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ promptsPage: 1 })
        expect(mockPromptsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: PROMPTS_PAGE_SIZE,
            offset: 0,
            topic: '',
            include_archived: true,
        })

        logic.actions.setPromptsPage(2)
        logic.actions.setNeedsImprovement(true)
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ promptsPage: 1 })
        expect(mockPromptsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: PROMPTS_PAGE_SIZE,
            offset: 0,
            topic: '',
            include_archived: true,
            needs_improvement: true,
        })

        logic.actions.setPromptsPage(2)
        logic.actions.setPromptsBranded(false)
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ promptsPage: 1 })
        expect(mockPromptsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            limit: PROMPTS_PAGE_SIZE,
            offset: 0,
            topic: '',
            include_archived: true,
            needs_improvement: true,
            branded: false,
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
        logic.actions.setPromptsTopic('pricing')
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

    it('flags a topics failure and clears it when a retry succeeds', async () => {
        mockPromptsTopics.mockRejectedValueOnce(new ApiError('Server error', 500))
        silenceKeaLoadersErrors()
        try {
            logic = contentAutopilotPromptsLogic()
            logic.mount()
            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({ promptTopicsError: true, promptTopics: [], promptsError: null })

            logic.actions.loadAeoPromptTopics()
            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({ promptTopicsError: false, promptTopics: EXAMPLE_PROMPT_TOPICS })
        } finally {
            resumeKeaLoadersErrors()
        }
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
})
