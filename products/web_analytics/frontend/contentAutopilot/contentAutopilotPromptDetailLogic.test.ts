import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import type { HogQLQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    aeoPromptsChecks,
    aeoPromptsList,
    aeoPromptsPartialUpdate,
    aeoPromptsRetrieve,
    aeoPromptsStats,
    aeoPromptsVersions,
} from '../generated/api'
import type { AEOPromptApi } from '../generated/api.schemas'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import {
    EXAMPLE_PROMPT_CHECKS,
    EXAMPLE_PROMPT_STATS,
    EXAMPLE_PROMPT_VERSIONS,
    EXAMPLE_PROMPTS,
} from './contentAutopilotStoryFixtures'

// The detail logic connects to the prompts list logic, which loads the list and topics on mount.
jest.mock('../generated/api', () => ({
    aeoPromptsList: jest.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
    aeoPromptsTopics: jest.fn().mockResolvedValue([]),
    aeoPromptsChecks: jest.fn(),
    aeoPromptsRetrieve: jest.fn(),
    aeoPromptsStats: jest.fn(),
    aeoPromptsVersions: jest.fn(),
    aeoPromptsPartialUpdate: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({ lemonToast: { error: jest.fn() } }))

const mockChecks = jest.mocked(aeoPromptsChecks)
const mockRetrieve = jest.mocked(aeoPromptsRetrieve)
const mockStats = jest.mocked(aeoPromptsStats)
const mockVersions = jest.mocked(aeoPromptsVersions)
const mockPartialUpdate = jest.mocked(aeoPromptsPartialUpdate)

const PROMPT = EXAMPLE_PROMPTS[0]
const TEAM_ID = String(MOCK_DEFAULT_TEAM.id)

describe('contentAutopilotPromptDetailLogic', () => {
    let logic: ReturnType<typeof contentAutopilotPromptDetailLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        mockRetrieve.mockResolvedValue(PROMPT)
        mockStats.mockResolvedValue(EXAMPLE_PROMPT_STATS)
        mockVersions.mockResolvedValue(EXAMPLE_PROMPT_VERSIONS)
        mockChecks.mockImplementation(async (_teamId, _promptId, params) => {
            const results = params?.engine
                ? EXAMPLE_PROMPT_CHECKS.filter((check) => check.engine === params.engine)
                : EXAMPLE_PROMPT_CHECKS
            return { count: results.length, next: null, previous: null, results }
        })
        logic = contentAutopilotPromptDetailLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the prompt, its stats, its versions and the latest answer of each engine', async () => {
        logic.actions.openPromptDetail(PROMPT.id)
        await expectLogic(logic).toFinishAllListeners()

        for (const engine of ['claude-web-search', 'openai-web-search', 'exa-answer']) {
            expect(mockChecks).toHaveBeenCalledWith(TEAM_ID, PROMPT.id, { engine, limit: 1 })
        }
        expect(logic.values.prompt?.id).toBe(PROMPT.id)
        expect(logic.values.engines).toEqual(['claude-web-search', 'openai-web-search', 'exa-answer'])
        expect(logic.values.activeEngine).toBe('claude-web-search')
        expect(logic.values.shownCheck?.id).toBe(EXAMPLE_PROMPT_CHECKS[0].id)
        expect(mockVersions).toHaveBeenCalledWith(TEAM_ID, PROMPT.id)
        expect(logic.values.versions).toEqual(EXAMPLE_PROMPT_VERSIONS)
        expect(logic.values.reportKpis?.days).toBe(30)
        expect(logic.values.consensusMatrix?.rows.map((row) => row.engine)).toEqual([
            'claude-web-search',
            'openai-web-search',
            'exa-answer',
        ])
    })

    it('scopes the report queries to the prompt and the stats window, and switches the visibility metric', async () => {
        logic.actions.openPromptDetail(PROMPT.id)
        await expectLogic(logic).toFinishAllListeners()

        const citedQuery = logic.values.visibilityQuery!
        expect(citedQuery.source.values).toEqual({ prompt_id: PROMPT.id, window_start: '2026-09-01 00:00:00' })
        expect(citedQuery.source.query).toContain('countIf(cited)')
        expect((logic.values.sourcesQuery!.source as HogQLQuery).values).toEqual(citedQuery.source.values)
        expect(logic.values.sentimentQuery!.source.values).toEqual(citedQuery.source.values)
        expect(logic.values.sentimentQuery!.source.query).toContain('brand_sentiment IS NOT NULL')

        logic.actions.setVisibilityMetric('mentioned')
        const mentionedQuery = logic.values.visibilityQuery!
        expect(mentionedQuery.source.query).toContain('{brand_pattern}')
        expect(mentionedQuery.source.values?.brand_pattern).toBe('\\b(example)\\b')

        // A new prompt starts over on the citation metric.
        logic.actions.openPromptDetail(EXAMPLE_PROMPTS[1].id)
        expect(logic.values.visibilityMetric).toBe('cited')
    })

    it('does not load versions for a prompt with one version', async () => {
        mockRetrieve.mockResolvedValue(EXAMPLE_PROMPTS[1])
        logic.actions.openPromptDetail(EXAMPLE_PROMPTS[1].id)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockVersions).not.toHaveBeenCalled()
        expect(logic.values.versions).toBeNull()
    })

    it.each([
        ['archives', true, { ...PROMPT, active: false, archived_at: '2026-10-01T00:00:00Z' }],
        ['restores', false, { ...PROMPT, active: false, archived_at: null }],
    ])('%s the prompt once the request settles, then refreshes the list', async (_name, archived, updated) => {
        logic.actions.openPromptDetail(PROMPT.id)
        await expectLogic(logic).toFinishAllListeners()
        let settle: () => void = () => {}
        mockPartialUpdate.mockReturnValue(
            new Promise<AEOPromptApi>((resolve) => {
                settle = () => resolve(updated)
            })
        )
        const listCalls = jest.mocked(aeoPromptsList).mock.calls.length

        logic.actions.setArchiveConfirming(true)
        logic.actions.setPromptArchived(archived)
        expect(logic.values.promptArchiving).toBe(true)

        settle()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockPartialUpdate).toHaveBeenCalledWith(TEAM_ID, PROMPT.id, { archived })
        expect(logic.values).toMatchObject({ prompt: updated, promptArchiving: false, archiveConfirming: false })
        expect(jest.mocked(aeoPromptsList).mock.calls.length).toBe(listCalls + 1)
    })

    it('shows an older check, then goes back to the latest answer of an engine', async () => {
        logic.actions.openPromptDetail(PROMPT.id)
        await expectLogic(logic).toFinishAllListeners()

        const older = EXAMPLE_PROMPT_CHECKS[2]
        logic.actions.selectCheck(older)
        expect(logic.values).toMatchObject({ activeEngine: older.engine, shownCheck: older })

        logic.actions.selectEngine('openai-web-search')
        expect(logic.values.selectedCheck).toBeNull()
        expect(logic.values.shownCheck?.id).toBe(EXAMPLE_PROMPT_CHECKS[1].id)
    })

    it('ignores responses for a prompt the user already left', async () => {
        const other = EXAMPLE_PROMPTS[1]
        let resolveFirstPrompt: (value: typeof PROMPT) => void = () => {}
        let resolveFirstStats: (value: typeof EXAMPLE_PROMPT_STATS) => void = () => {}
        mockRetrieve.mockImplementationOnce(() => new Promise((resolve) => (resolveFirstPrompt = resolve)))
        mockStats.mockImplementationOnce(() => new Promise((resolve) => (resolveFirstStats = resolve)))

        logic.actions.openPromptDetail(PROMPT.id)
        mockRetrieve.mockResolvedValue(other)
        await expectLogic(logic, () => logic.actions.openPromptDetail(other.id)).toDispatchActions([
            'loadAeoPromptSuccess',
            'loadAeoPromptStatsSuccess',
        ])
        resolveFirstPrompt(PROMPT)
        resolveFirstStats(EXAMPLE_PROMPT_STATS)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.prompt?.id).toBe(other.id)
        const latestCheckPrompts = mockChecks.mock.calls
            .filter(([, , params]) => params?.limit === 1)
            .map(([, id]) => id)
        expect(new Set(latestCheckPrompts)).toEqual(new Set([other.id]))
    })

    it.each([
        ['not_found', new ApiError('Not found', 404)],
        ['failed', new ApiError('Server error', 500)],
    ])('reports %s when the prompt fails to load', async (expected, error) => {
        mockRetrieve.mockRejectedValue(error)
        silenceKeaLoadersErrors()
        try {
            logic.actions.openPromptDetail(PROMPT.id)
            await expectLogic(logic).toFinishAllListeners().toMatchValues({ detailError: expected, prompt: null })
        } finally {
            resumeKeaLoadersErrors()
        }
    })
})
