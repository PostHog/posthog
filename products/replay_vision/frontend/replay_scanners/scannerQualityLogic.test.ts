import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    environmentVisionQuotaRetrieve,
    visionScannersObservationsList,
    visionScannersObservationsStatsRetrieve,
    visionScannersPromptSuggestionsCurrentRetrieve,
    visionScannersPromptSuggestionsEvaluateCreate,
    visionScannersPromptSuggestionsGenerateCreate,
} from '../generated/api'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { QUALITY_PAGE_SIZE, RatedFilterValue, scannerQualityLogic } from './scannerQualityLogic'

jest.mock('../generated/api', () => ({
    environmentVisionQuotaRetrieve: jest.fn(),
    visionScannersObservationsList: jest.fn(),
    visionScannersObservationsStatsRetrieve: jest.fn(),
    visionScannersPromptSuggestionsCurrentRetrieve: jest.fn(),
    visionScannersPromptSuggestionsGenerateCreate: jest.fn(),
    visionScannersPromptSuggestionsApplyCreate: jest.fn(),
    visionScannersPromptSuggestionsDismissCreate: jest.fn(),
    visionScannersPromptSuggestionsEvaluateCreate: jest.fn(),
    visionScannersPromptSuggestionsList: jest.fn(),
}))

const TEAM_ID = String(MOCK_DEFAULT_TEAM.id)

const PENDING_SUGGESTION = {
    id: 'sug-1',
    status: 'pending',
    suggested_prompt: 'better prompt',
    base_prompt: 'old prompt',
    rationale: 'tightened',
    based_on_up: 1,
    based_on_down: 2,
    scanner_version: 1,
    created_at: '2026-07-01T00:00:00Z',
    created_by: null,
    applied_at: null,
    applied_by: null,
}

describe('scannerQualityLogic', () => {
    let logic: ReturnType<typeof scannerQualityLogic.build>

    const mountLogic = async (): Promise<void> => {
        logic = scannerQualityLogic({ scannerId: 'scan-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess', 'loadCurrentSuggestionSuccess'])
    }

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        ;(visionScannersObservationsList as jest.Mock).mockResolvedValue({
            results: [
                { id: 'obs-1', session_id: 'sess-1', status: 'succeeded', label: null },
                { id: 'obs-2', session_id: 'sess-2', status: 'succeeded', label: null },
            ],
            count: 2,
        })
        ;(visionScannersObservationsStatsRetrieve as jest.Mock).mockResolvedValue({
            labels: { up_total: 0, down_total: 0, by_day: [], by_rating_day: [], version_markers: [] },
        })
        ;(visionScannersPromptSuggestionsCurrentRetrieve as jest.Mock).mockResolvedValue({
            suggestion: PENDING_SUGGESTION,
            stale: false,
            rated_count: 3,
            evaluation_session_cap: 10,
        })
        ;(visionScannersPromptSuggestionsGenerateCreate as jest.Mock).mockResolvedValue({
            ...PENDING_SUGGESTION,
            id: 'sug-2',
        })
        ;(environmentVisionQuotaRetrieve as jest.Mock).mockResolvedValue({
            monthly_quota: 3000,
            usage_this_month: 100,
            remaining: 2900,
            exhausted: false,
        })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each<[RatedFilterValue, Record<string, unknown>]>([
        ['all', { status: 'succeeded', limit: QUALITY_PAGE_SIZE, order_by: '-created_at' }],
        ['rated', { status: 'succeeded', limit: QUALITY_PAGE_SIZE, labeled: true, order_by: '-created_at' }],
        ['unrated', { status: 'succeeded', limit: QUALITY_PAGE_SIZE, labeled: false, order_by: '-created_at' }],
    ])('the "%s" filter requests the matching observation set', async (filter, expectedParams) => {
        await mountLogic()
        logic.actions.setRatedFilter(filter)
        await expectLogic(logic).toFinishAllListeners()

        expect(visionScannersObservationsList).toHaveBeenLastCalledWith(TEAM_ID, 'scan-1', expectedParams)
    })

    it('a stale current-suggestion read does not clobber a fresh generate', async () => {
        await mountLogic()
        let resolveStale: (value: unknown) => void = () => {}
        ;(visionScannersPromptSuggestionsCurrentRetrieve as jest.Mock).mockImplementationOnce(
            () => new Promise((resolve) => (resolveStale = resolve))
        )

        logic.actions.loadCurrentSuggestion()
        logic.actions.generateSuggestion()
        await expectLogic(logic).toDispatchActions(['generateSuggestionSuccess'])
        resolveStale({ suggestion: PENDING_SUGGESTION, stale: false, rated_count: 3 })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.currentSuggestion?.id).toEqual('sug-2')
    })

    it('a filter change during an in-flight load drops the stale response', async () => {
        await mountLogic()
        let resolveStale: (value: unknown) => void = () => {}
        ;(visionScannersObservationsList as jest.Mock)
            .mockImplementationOnce(() => new Promise((resolve) => (resolveStale = resolve)))
            .mockResolvedValueOnce({ results: [{ id: 'fresh', session_id: 'sess-9', status: 'succeeded' }], count: 1 })

        logic.actions.setRatedFilter('rated')
        logic.actions.setRatedFilter('all')
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
        resolveStale({ results: [{ id: 'stale', session_id: 'sess-0', status: 'succeeded' }], count: 1 })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.observations.map((obs) => obs.id)).toEqual(['fresh'])
    })

    it('an inline rating updates the row so a remount does not resurrect a stale label', async () => {
        await mountLogic()
        logic.actions.labelChanged('obs-2', { is_correct: false, feedback: 'should be yes' })

        expect(logic.values.observations.find((obs) => obs.id === 'obs-2')?.label).toEqual({
            is_correct: false,
            feedback: 'should be yes',
        })
        expect(logic.values.observations.find((obs) => obs.id === 'obs-1')?.label).toBeNull()
    })

    it('evaluate stores the running test on the current suggestion', async () => {
        const runningEvaluation = {
            status: 'running',
            started_at: '2026-07-05T00:00:00Z',
            finished_at: null,
            total: 0,
            labels_fingerprint: '',
            results: [],
            summary: null,
        }
        ;(visionScannersPromptSuggestionsEvaluateCreate as jest.Mock).mockResolvedValue({
            ...PENDING_SUGGESTION,
            evaluation: runningEvaluation,
        })
        await mountLogic()
        logic.actions.evaluateSuggestion('sug-1')
        await expectLogic(logic).toDispatchActions(['evaluateSuggestionSuccess'])

        expect(visionScannersPromptSuggestionsEvaluateCreate).toHaveBeenCalledWith(TEAM_ID, 'scan-1', 'sug-1')
        expect(logic.values.currentSuggestion?.evaluation).toEqual(runningEvaluation)
        expect(logic.values.evaluating).toBe(false)
    })

    it('a running test refreshes the quota snapshot on every poll', async () => {
        // A test run spends quota per session, so stale quota numbers here mean the cost line lies.
        ;(visionScannersPromptSuggestionsCurrentRetrieve as jest.Mock).mockResolvedValue({
            suggestion: {
                ...PENDING_SUGGESTION,
                evaluation: { status: 'running', results: [], total: 2, summary: null },
            },
            stale: false,
            rated_count: 3,
            evaluation_session_cap: 10,
        })
        await mountLogic()

        // Matches the listener-driven refresh: the mount-time loadQuota is already behind the pointer.
        await expectLogic(logic).toDispatchActions([visionQuotaLogic.actionTypes.loadQuota])
    })

    it('never auto-generates on load, even when the recommendation is stale', async () => {
        // Generation is expensive. The daily backend refresh owns freshness, the tab only reports it.
        ;(visionScannersPromptSuggestionsCurrentRetrieve as jest.Mock).mockResolvedValue({
            suggestion: PENDING_SUGGESTION,
            stale: true,
            rated_count: 3,
            evaluation_session_cap: 10,
        })
        await mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        expect(visionScannersPromptSuggestionsGenerateCreate).not.toHaveBeenCalled()
        expect(logic.values.suggestionStale).toBe(true)
    })
})
