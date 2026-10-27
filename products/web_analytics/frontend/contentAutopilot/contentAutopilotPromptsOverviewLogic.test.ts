import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { aeoPromptsList, aeoPromptsOverview, aeoPromptsPartialUpdate, aeoPromptsTopics } from '../generated/api'
import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { OVERVIEW_DAYS, contentAutopilotPromptsOverviewLogic } from './contentAutopilotPromptsOverviewLogic'
import { EXAMPLE_PROMPT_SET_OVERVIEW, EXAMPLE_PROMPT_TOPICS, EXAMPLE_PROMPTS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    aeoPromptsList: jest.fn(),
    aeoPromptsTopics: jest.fn(),
    aeoPromptsPartialUpdate: jest.fn(),
    aeoPromptsOverview: jest.fn(),
}))

const mockOverview = jest.mocked(aeoPromptsOverview)

describe('contentAutopilotPromptsOverviewLogic', () => {
    let logic: ReturnType<typeof contentAutopilotPromptsOverviewLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.mocked(aeoPromptsList).mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: EXAMPLE_PROMPTS,
        })
        jest.mocked(aeoPromptsTopics).mockResolvedValue(EXAMPLE_PROMPT_TOPICS)
        mockOverview.mockResolvedValue(EXAMPLE_PROMPT_SET_OVERVIEW)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the overview on mount and builds the queries from its window', async () => {
        logic = contentAutopilotPromptsOverviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            overview: EXAMPLE_PROMPT_SET_OVERVIEW,
            overviewError: null,
            hasChecks: true,
        })
        expect(mockOverview).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), { days: OVERVIEW_DAYS })
        expect(logic.values.citationQuery?.source.values).toEqual({ window_start: '2026-09-01 00:00:00' })
        expect(logic.values.sourcesQuery?.source).toMatchObject({ values: { window_start: '2026-09-01 00:00:00' } })
    })

    it.each([
        ['forbidden', new ApiError('This feature is not available.', 403)],
        ['failed', new ApiError('Server error', 500)],
    ])('reports a %s error when the overview fails to load', async (expected, error) => {
        mockOverview.mockRejectedValue(error)
        silenceKeaLoadersErrors()
        try {
            logic = contentAutopilotPromptsOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ overviewError: expected, overview: null })
        } finally {
            resumeKeaLoadersErrors()
        }
    })

    it('filters the prompt list when a topic is picked', async () => {
        logic = contentAutopilotPromptsOverviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.selectOverviewTopic('Session replay')
        await expectLogic(contentAutopilotPromptsLogic)
            .toDispatchActions(['setPromptsTopic'])
            .toMatchValues({ promptsTopic: 'Session replay' })
    })

    it('reloads the overview after a prompt is turned off', async () => {
        jest.mocked(aeoPromptsPartialUpdate).mockResolvedValue({ ...EXAMPLE_PROMPTS[0], active: false })
        logic = contentAutopilotPromptsOverviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockOverview).toHaveBeenCalledTimes(1)

        contentAutopilotPromptsLogic.actions.setPromptActive(EXAMPLE_PROMPTS[0].id, false)
        await expectLogic(logic).toDispatchActions(['setPromptActiveSuccess', 'loadPromptSetOverviewSuccess'])
        expect(mockOverview).toHaveBeenCalledTimes(2)
    })
})
