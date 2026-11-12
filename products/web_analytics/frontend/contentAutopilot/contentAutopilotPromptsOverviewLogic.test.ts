import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import type { HogQLQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    aeoPromptsList,
    aeoPromptsOverview,
    aeoPromptsPartialUpdate,
    aeoPromptsRetrieve,
    aeoPromptsTopics,
} from '../generated/api'
import { contentAutopilotBrandedLogic } from './contentAutopilotBrandedLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { OVERVIEW_DAYS, contentAutopilotPromptsOverviewLogic } from './contentAutopilotPromptsOverviewLogic'
import { EXAMPLE_PROMPT_SET_OVERVIEW, EXAMPLE_PROMPT_TOPICS, EXAMPLE_PROMPTS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    aeoPromptsList: jest.fn(),
    aeoPromptsTopics: jest.fn(),
    aeoPromptsPartialUpdate: jest.fn(),
    aeoPromptsOverview: jest.fn(),
    aeoPromptsRetrieve: jest.fn(),
    aeoPromptsStats: jest.fn(),
    aeoPromptsChecks: jest.fn(),
}))

const mockOverview = jest.mocked(aeoPromptsOverview)

describe('contentAutopilotPromptsOverviewLogic', () => {
    let logic: ReturnType<typeof contentAutopilotPromptsOverviewLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        // The branded segment persists in local storage, so a choice made in one test must not leak into the next.
        localStorage.clear()
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
        expect(mockOverview).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            days: OVERVIEW_DAYS,
            branded: 'non_branded',
        })
        expect(logic.values.citationQuery?.source.values).toEqual({
            window_start: '2026-09-01 00:00:00',
            brand_pattern: '\\b(example)\\b',
        })
        // The legend shows the engine's display name, built into the SQL from the shared label map.
        expect(logic.values.citationQuery?.source.query).toContain("engine = 'claude-web-search', 'Claude'")
        expect(logic.values.sourcesQuery?.source).toMatchObject({ values: { window_start: '2026-09-01 00:00:00' } })
    })

    it.each([
        ['all', ['example'], null],
        ['branded', ['example'], 'AND match(lower(prompt_text), {brand_pattern})'],
        ['non_branded', ['example'], 'AND NOT match(lower(prompt_text), {brand_pattern})'],
        ['branded', [], 'AND false'],
        ['non_branded', [], null],
    ] as const)(
        'reloads the %s segment with brand names %j and filters the set queries the same way',
        async (segment, brandNames, where) => {
            mockOverview.mockImplementation(async (_, params) => ({
                ...EXAMPLE_PROMPT_SET_OVERVIEW,
                brand_names: [...brandNames],
                branded: params?.branded ?? 'all',
            }))
            logic = contentAutopilotPromptsOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            contentAutopilotBrandedLogic.actions.setBrandedSegment(segment, 'overview')
            await expectLogic(logic).toDispatchActions(['loadPromptSetOverviewSuccess']).toFinishAllListeners()

            expect(mockOverview).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
                days: OVERVIEW_DAYS,
                branded: segment,
            })
            const queries = [logic.values.citationQuery?.source, logic.values.sourcesQuery?.source].map(
                (source) => (source as HogQLQuery).query
            )
            for (const query of queries) {
                if (where) {
                    expect(query).toContain(where)
                } else {
                    expect(query).not.toContain('prompt_text')
                    expect(query).not.toContain('AND false')
                }
            }
        }
    )

    it('keeps the chosen segment after the logic mounts again', async () => {
        logic = contentAutopilotPromptsOverviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        contentAutopilotBrandedLogic.actions.setBrandedSegment('all', 'overview')
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()

        initKeaTests()
        logic = contentAutopilotPromptsOverviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ brandedSegment: 'all' })
        expect(mockOverview).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            days: OVERVIEW_DAYS,
            branded: 'all',
        })
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

    it('keeps the overview when a superseded request fails', async () => {
        let rejectFirst: (error: Error) => void = () => {}
        mockOverview.mockImplementationOnce(
            () =>
                new Promise((_, reject) => {
                    rejectFirst = reject
                })
        )
        logic = contentAutopilotPromptsOverviewLogic()
        logic.mount()
        logic.actions.loadPromptSetOverview()
        await expectLogic(logic)
            .toDispatchActions(['loadPromptSetOverviewSuccess'])
            .toMatchValues({ overview: EXAMPLE_PROMPT_SET_OVERVIEW })

        rejectFirst(new ApiError('Server error', 500))
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ overview: EXAMPLE_PROMPT_SET_OVERVIEW, overviewError: null })
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

    it('opens a prompt picked from the searches on the prompts tab', async () => {
        jest.mocked(aeoPromptsRetrieve).mockResolvedValue(EXAMPLE_PROMPTS[1])
        logic = contentAutopilotPromptsOverviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openOverviewSearchPrompt(EXAMPLE_PROMPTS[1].id)
        await expectLogic(logic).toDispatchActions(['setWorkspaceTab', 'openPromptDetail'])
        expect(contentAutopilotLogic.values.workspaceTab).toEqual('prompts')
        expect(contentAutopilotPromptDetailLogic.values.promptId).toEqual(EXAMPLE_PROMPTS[1].id)
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
