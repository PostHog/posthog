import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { aeoPromptsList, aeoPromptsPartialUpdate, aeoPromptsTopics } from '../generated/api'
import type { AEOPromptApi } from '../generated/api.schemas'
import { PROMPTS_PAGE_SIZE, contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { EXAMPLE_PROMPT_TOPICS, EXAMPLE_PROMPTS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    aeoPromptsList: jest.fn(),
    aeoPromptsTopics: jest.fn(),
    aeoPromptsPartialUpdate: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({ lemonToast: { error: jest.fn() } }))

const mockPromptsList = jest.mocked(aeoPromptsList)
const mockPromptsTopics = jest.mocked(aeoPromptsTopics)
const mockPromptsPartialUpdate = jest.mocked(aeoPromptsPartialUpdate)

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

    it('resets to the first page and sends the filters when the topic or archived filter changes', async () => {
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
})
