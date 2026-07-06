import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    visionScannersObservationsList,
    visionScannersObservationsStatsRetrieve,
    visionScannersPromptSuggestionsApplyCreate,
    visionScannersPromptSuggestionsCurrentRetrieve,
    visionScannersPromptSuggestionsDismissCreate,
    visionScannersPromptSuggestionsGenerateCreate,
} from '../generated/api'
import { QUALITY_PAGE_SIZE, RatedFilterValue, scannerQualityLogic } from './scannerQualityLogic'

jest.mock('../generated/api', () => ({
    visionScannersObservationsList: jest.fn(),
    visionScannersObservationsStatsRetrieve: jest.fn(),
    visionScannersPromptSuggestionsCurrentRetrieve: jest.fn(),
    visionScannersPromptSuggestionsGenerateCreate: jest.fn(),
    visionScannersPromptSuggestionsApplyCreate: jest.fn(),
    visionScannersPromptSuggestionsDismissCreate: jest.fn(),
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
        // Any order: the observations load sits behind a short debounce, so it can resolve last.
        await expectLogic(logic).toDispatchActionsInAnyOrder([
            'loadObservationsSuccess',
            'loadCurrentSuggestionSuccess',
        ])
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
        })
        ;(visionScannersPromptSuggestionsGenerateCreate as jest.Mock).mockResolvedValue({
            ...PENDING_SUGGESTION,
            id: 'sug-2',
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

    it('an inline rating updates the row so a remount does not resurrect a stale label', async () => {
        await mountLogic()
        logic.actions.labelChanged('obs-2', { is_correct: false, feedback: 'should be yes' })

        expect(logic.values.observations.find((obs) => obs.id === 'obs-2')?.label).toEqual({
            is_correct: false,
            feedback: 'should be yes',
        })
        expect(logic.values.observations.find((obs) => obs.id === 'obs-1')?.label).toBeNull()
    })

    it('never auto-generates on load, even when the recommendation is stale', async () => {
        // Generation is expensive. The daily backend refresh owns freshness, the tab only reports it.
        ;(visionScannersPromptSuggestionsCurrentRetrieve as jest.Mock).mockResolvedValue({
            suggestion: PENDING_SUGGESTION,
            stale: true,
            rated_count: 3,
        })
        await mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        expect(visionScannersPromptSuggestionsGenerateCreate).not.toHaveBeenCalled()
        expect(logic.values.suggestionStale).toBe(true)
    })

    it('page changes request the matching offset and sort changes map to order_by and reset the page', async () => {
        await mountLogic()

        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()
        expect(visionScannersObservationsList).toHaveBeenLastCalledWith(
            TEAM_ID,
            'scan-1',
            expect.objectContaining({ offset: QUALITY_PAGE_SIZE })
        )

        logic.actions.setSort({ columnKey: 'created_at', order: 1 })
        await expectLogic(logic).toFinishAllListeners()
        const lastParams = (visionScannersObservationsList as jest.Mock).mock.calls.at(-1)![2]
        expect(lastParams.order_by).toBe('created_at')
        expect(lastParams.offset).toBeUndefined()
    })

    it('applying updates the card and resets the loading flag', async () => {
        ;(visionScannersPromptSuggestionsApplyCreate as jest.Mock).mockResolvedValue({
            ...PENDING_SUGGESTION,
            status: 'applied',
            applied_at: '2026-07-02T00:00:00Z',
        })
        await mountLogic()

        logic.actions.applySuggestion('sug-1')
        await expectLogic(logic).toDispatchActions(['applySuggestionSuccess'])

        expect(visionScannersPromptSuggestionsApplyCreate).toHaveBeenCalledWith(TEAM_ID, 'scan-1', 'sug-1')
        expect(logic.values.currentSuggestion?.status).toBe('applied')
        expect(logic.values.applying).toBe(false)
    })

    it.each([
        ['applySuggestion', visionScannersPromptSuggestionsApplyCreate, 'applying'],
        ['dismissSuggestion', visionScannersPromptSuggestionsDismissCreate, 'dismissing'],
        ['generateSuggestion', visionScannersPromptSuggestionsGenerateCreate, 'generating'],
    ] as const)('a failed %s resets its loading flag so the button unsticks', async (action, mockFn, flag) => {
        ;(mockFn as jest.Mock).mockRejectedValue({ detail: 'nope' })
        await mountLogic()

        logic.actions[action]('sug-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values[flag]).toBe(false)
        expect(logic.values.currentSuggestion?.status).toBe('pending')
    })

    it('a stale current-suggestion fetch cannot revert a mutation that landed meanwhile', async () => {
        await mountLogic()
        let resolveCurrent: (value: unknown) => void = () => {}
        ;(visionScannersPromptSuggestionsCurrentRetrieve as jest.Mock).mockImplementationOnce(
            () => new Promise((resolve) => (resolveCurrent = resolve))
        )
        ;(visionScannersPromptSuggestionsApplyCreate as jest.Mock).mockResolvedValue({
            ...PENDING_SUGGESTION,
            status: 'applied',
        })

        logic.actions.loadCurrentSuggestion()
        logic.actions.applySuggestion('sug-1')
        await expectLogic(logic).toDispatchActions(['applySuggestionSuccess'])

        resolveCurrent({ suggestion: PENDING_SUGGESTION, stale: false, rated_count: 3 })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.currentSuggestion?.status).toBe('applied')
    })

    it('an out-of-order observations response cannot overwrite the newer filter', async () => {
        await mountLogic()
        let resolveSlow: (value: unknown) => void = () => {}
        ;(visionScannersObservationsList as jest.Mock)
            .mockImplementationOnce(() => new Promise((resolve) => (resolveSlow = resolve)))
            .mockResolvedValueOnce({
                results: [{ id: 'obs-rated', session_id: 'sess-r', status: 'succeeded', label: { is_correct: true } }],
                count: 1,
            })

        logic.actions.setRatedFilter('all')
        // Let the slow request pass its debounce and go out before the next click.
        await new Promise((resolve) => setTimeout(resolve, 20))
        logic.actions.setRatedFilter('rated')
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])

        resolveSlow({
            results: [{ id: 'obs-stale', session_id: 'sess-s', status: 'succeeded', label: null }],
            count: 99,
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.observations.map((obs) => obs.id)).toEqual(['obs-rated'])
        expect(logic.values.total).toBe(1)
    })

    it('a burst of inline ratings reloads the stats and recommendation once', async () => {
        await mountLogic()
        const statsCallsBefore = (visionScannersObservationsStatsRetrieve as jest.Mock).mock.calls.length
        const currentCallsBefore = (visionScannersPromptSuggestionsCurrentRetrieve as jest.Mock).mock.calls.length

        logic.actions.labelChanged('obs-1', { is_correct: true, feedback: '' })
        logic.actions.labelChanged('obs-2', { is_correct: false, feedback: 'x' })
        await expectLogic(logic).toFinishAllListeners()

        expect((visionScannersObservationsStatsRetrieve as jest.Mock).mock.calls.length).toBe(statsCallsBefore + 1)
        expect((visionScannersPromptSuggestionsCurrentRetrieve as jest.Mock).mock.calls.length).toBe(
            currentCallsBefore + 1
        )
    })
})
