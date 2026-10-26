import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import {
    warehouseSavedQueriesCheckIncrementalCreate,
    warehouseSavedQueriesRetrieve,
} from 'products/data_warehouse/frontend/generated/api'

import {
    warehouseSuggestionsAcceptCreate,
    warehouseSuggestionsDismissCreate,
    warehouseSuggestionsList,
    warehouseSuggestionsResumeCreate,
    warehouseSuggestionsStatusRetrieve,
} from './generated/api'
import type { WarehouseSuggestionApi, WarehouseSuggestionStatusApi } from './generated/api.schemas'
import { intervalForSeconds } from './refreshIntervals'
import { ROW_LEAVE_MS, StripState, SuggestionSurface, warehouseSuggestionsLogic } from './warehouseSuggestionsLogic'

jest.mock('./generated/api', () => ({
    warehouseSuggestionsAcceptCreate: jest.fn(),
    warehouseSuggestionsDismissCreate: jest.fn(),
    warehouseSuggestionsList: jest.fn(),
    warehouseSuggestionsResumeCreate: jest.fn(),
    warehouseSuggestionsStatusRetrieve: jest.fn(),
}))
jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    warehouseSavedQueriesRetrieve: jest.fn(),
    warehouseSavedQueriesCheckIncrementalCreate: jest.fn(),
}))

const mockList = warehouseSuggestionsList as jest.MockedFunction<typeof warehouseSuggestionsList>
const mockStatus = warehouseSuggestionsStatusRetrieve as jest.MockedFunction<typeof warehouseSuggestionsStatusRetrieve>
const mockAccept = warehouseSuggestionsAcceptCreate as jest.MockedFunction<typeof warehouseSuggestionsAcceptCreate>
const mockDismiss = warehouseSuggestionsDismissCreate as jest.MockedFunction<typeof warehouseSuggestionsDismissCreate>
const mockResume = warehouseSuggestionsResumeCreate as jest.MockedFunction<typeof warehouseSuggestionsResumeCreate>
const mockSavedQuery = warehouseSavedQueriesRetrieve as jest.MockedFunction<typeof warehouseSavedQueriesRetrieve>
const mockCheck = warehouseSavedQueriesCheckIncrementalCreate as jest.MockedFunction<
    typeof warehouseSavedQueriesCheckIncrementalCreate
>

const ACTIVE_STATUS: WarehouseSuggestionStatusApi = {
    enabled: true,
    eligible: true,
    days_with_data: 30,
    window_days: 30,
    paused_reason: null,
    refreshed_at: '2026-10-07T08:30:00Z',
}

const MATERIALIZE: WarehouseSuggestionApi = {
    id: 'suggestion-1',
    kind: 'materialize',
    subject_kind: 'saved_query',
    subject_id: 'view-1',
    payload: {
        subject_name: 'orders',
        refresh_interval_seconds: 86400,
        saves_seconds_per_month: 1200,
        saves_bytes_per_month: 0,
        freshness_today_seconds: null,
        freshness_after_seconds: 86400,
        live_sources: { names: [], hidden_count: 0 },
        unknown_sources: { names: [], hidden_count: 0 },
        refresh_mode: 'full',
        refresh_interval_basis: 'savings',
    },
    payload_version: 1,
    evidence: { human_requests: 200, human_users: 6, human_days: 25 },
    evidence_window_start: '2026-09-07T00:00:00Z',
    evidence_window_end: '2026-10-07T00:00:00Z',
    last_seen_at: '2026-10-07T08:30:00Z',
    status: 'proposed',
    surfaced_at: '2026-10-07T08:30:00Z',
    reviewed_by: null,
    reviewed_at: null,
    dismissal_reason: null,
    dismissal_note: null,
    created_asset: null,
    asset_outcome: null,
    realized_seconds_saved_per_month: null,
    realized_bytes_saved_per_month: null,
    can_act: true,
}

function materialize(id: string, savesSeconds: number, savesBytes = 0): WarehouseSuggestionApi {
    return {
        ...MATERIALIZE,
        id,
        subject_id: `view-${id}`,
        payload: { ...MATERIALIZE.payload, saves_seconds_per_month: savesSeconds, saves_bytes_per_month: savesBytes },
    }
}

const INCREMENTAL: WarehouseSuggestionApi = {
    ...MATERIALIZE,
    id: 'suggestion-incremental',
    payload: {
        ...MATERIALIZE.payload,
        refresh_mode: 'incremental',
        incremental_key: 'day',
        unique_key: ['day', 'plan'],
        lookback_seconds: 3600,
    },
}

function unmaterialize(id: string, refreshSeconds: number, liveSeconds: number): WarehouseSuggestionApi {
    return {
        ...MATERIALIZE,
        id,
        kind: 'unmaterialize',
        subject_id: `view-${id}`,
        payload: {
            subject_name: id,
            refresh_seconds_per_month: refreshSeconds,
            refresh_bytes_per_month: 0,
            live_seconds_per_month: liveSeconds,
            live_bytes_per_month: 0,
            read_seconds: 4,
        },
    }
}

const DEPRECATE: WarehouseSuggestionApi = {
    ...MATERIALIZE,
    id: 'suggestion-deprecate',
    kind: 'deprecate',
    payload: { subject_name: 'old_rollup', refresh_seconds_per_month: 5400, refresh_bytes_per_month: 0 },
}

function certification(id: string, kind: 'certify' | 'deprecate'): WarehouseSuggestionApi {
    return { ...MATERIALIZE, id, kind, subject_kind: 'table', payload: { subject_name: id } }
}

function page(results: WarehouseSuggestionApi[]): Awaited<ReturnType<typeof warehouseSuggestionsList>> {
    return { count: results.length, results } as Awaited<ReturnType<typeof warehouseSuggestionsList>>
}

describe('warehouseSuggestionsLogic', () => {
    let logic: ReturnType<typeof warehouseSuggestionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockSavedQuery.mockReset()
        mockCheck.mockReset()
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')
        jest.spyOn(lemonToast, 'success').mockImplementation(() => 'toast')
        mockStatus.mockResolvedValue(ACTIVE_STATUS)
        mockList.mockResolvedValue(page([MATERIALIZE]))
    })

    afterEach(() => logic?.unmount())

    async function checksRequested(count: number): Promise<void> {
        while (mockCheck.mock.calls.length < count) {
            await new Promise((resolve) => setTimeout(resolve, 0))
        }
    }

    async function mountLogic(
        surface: SuggestionSurface = 'models',
        onViewAccepted?: (suggestion: WarehouseSuggestionApi) => void
    ): Promise<void> {
        logic = warehouseSuggestionsLogic({ surface, onViewAccepted })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSuggestionsSuccess', 'loadStatusSuccess'])
    }

    it.each<[string, Partial<WarehouseSuggestionStatusApi>, WarehouseSuggestionApi[], StripState]>([
        ['active with an open suggestion', {}, [MATERIALIZE], 'active'],
        ['hidden when a surfaced batch is empty', {}, [], 'hidden'],
        ['hidden while waiting for a slot', {}, [{ ...MATERIALIZE, surfaced_at: null }], 'hidden'],
        ['warming up before a full window', { days_with_data: 12 }, [], 'warming_up'],
        ['not eligible', { eligible: false }, [], 'not_eligible'],
        ['hidden before the first run', { refreshed_at: null, eligible: false }, [], 'hidden'],
    ])('strip state is %s', async (_name, status, results, expected) => {
        mockStatus.mockResolvedValue({ ...ACTIVE_STATUS, ...status })
        mockList.mockResolvedValue(page(results))

        await mountLogic()

        expect(logic.values.stripState).toEqual(expected)
    })

    it('stays hidden when the backend says the feature is off, even if the other request fails differently', async () => {
        mockStatus.mockRejectedValue(new ApiError('forbidden', 403, undefined, { detail: 'not enabled' }))
        mockList.mockRejectedValue(new ApiError('server error', 500, undefined, { detail: 'boom' }))
        logic = warehouseSuggestionsLogic({ surface: 'models' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSuggestionsFailure', 'loadStatusFailure'])

        expect(logic.values.stripState).toEqual('hidden')
    })

    it('keeps the list and the open dialog when a background reload fails', async () => {
        await mountLogic()
        logic.actions.openReview()
        mockList.mockRejectedValue(new ApiError('server error', 500, undefined, { detail: 'boom' }))

        logic.actions.loadSuggestions()
        await expectLogic(logic).toDispatchActions(['loadSuggestionsFailure'])

        expect(logic.values.stripState).toEqual('active')
        expect(logic.values.reviewOpen).toBe(true)
    })

    it.each(['status', 'list'])(
        'shows the error state when the %s request fails while the other succeeds, and retry loads both again',
        async (failing) => {
            let finishOther: () => void = () => {}
            const otherSettles = new Promise<void>((resolve) => (finishOther = resolve))
            if (failing === 'status') {
                mockStatus.mockRejectedValueOnce(new Error('down'))
                mockList.mockImplementationOnce(async () => {
                    await otherSettles
                    return page([MATERIALIZE])
                })
            } else {
                mockList.mockRejectedValueOnce(new Error('down'))
                mockStatus.mockImplementationOnce(async () => {
                    await otherSettles
                    return ACTIVE_STATUS
                })
            }
            logic = warehouseSuggestionsLogic({ surface: 'models' })
            logic.mount()
            await expectLogic(logic).toDispatchActions([
                failing === 'status' ? 'loadStatusFailure' : 'loadSuggestionsFailure',
            ])
            finishOther()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.stripState).toEqual('error')

            logic.actions.reload()

            await expectLogic(logic).toDispatchActions(['loadSuggestionsSuccess', 'loadStatusSuccess'])
            expect(logic.values.stripState).toEqual('active')
        }
    )

    it('keeps a card hidden when the list reloads while its dismiss is still running', async () => {
        let finish: (value: WarehouseSuggestionApi) => void = () => {}
        mockDismiss.mockReturnValue(new Promise((resolve) => (finish = resolve)))
        await mountLogic()

        logic.actions.dismissSuggestion(MATERIALIZE.id, 'not_now')
        logic.actions.loadSuggestions()
        await expectLogic(logic).toDispatchActions(['loadSuggestionsSuccess'])

        expect(logic.values.surfaceSuggestions).toEqual([])
        finish({ ...MATERIALIZE, status: 'dismissed' })
    })

    it('ignores a second accept while the first is in flight', async () => {
        let finish: (value: WarehouseSuggestionApi) => void = () => {}
        mockAccept.mockReturnValue(new Promise((resolve) => (finish = resolve)))
        await mountLogic()

        logic.actions.acceptSuggestion(MATERIALIZE.id, { refresh_interval_seconds: 86400 })
        logic.actions.acceptSuggestion(MATERIALIZE.id, { refresh_interval_seconds: 86400 })
        finish({ ...MATERIALIZE, status: 'accepted' })
        await expectLogic(logic).toDispatchActions(['suggestionAccepted'])

        expect(mockAccept).toHaveBeenCalledTimes(1)
        expect(logic.values.surfaceSuggestions).toEqual([])
    })

    it.each([
        ['someone else decided it first', 409],
        ['its view or table was deleted', 404],
    ])('restores a dismissed card and reloads when %s', async (_name, status) => {
        mockDismiss.mockRejectedValue(new ApiError('stale', status, undefined, { detail: 'stale' }))
        await mountLogic()

        logic.actions.dismissSuggestion(MATERIALIZE.id, 'not_now')

        await expectLogic(logic).toDispatchActions(['restoreSuggestion', 'loadSuggestions', 'loadSuggestionsSuccess'])
        expect(logic.values.surfaceSuggestions.map((suggestion) => suggestion.id)).toEqual([MATERIALIZE.id])
    })

    it.each(['refresh_interval_seconds', 'refresh_mode', 'incremental_key', 'unique_key', 'lookback_seconds'])(
        'keeps the materialize dialog open with the error when the backend refuses %s',
        async (attr) => {
            mockAccept.mockRejectedValue(new ApiError('refused', 400, undefined, { detail: 'Not allowed.', attr }))
            await mountLogic()
            logic.actions.openMaterializeModal(MATERIALIZE.id)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.confirmMaterialize()

            await expectLogic(logic).toDispatchActions(['setMaterializeError'])
            expect(logic.values.materializeError).toEqual('Not allowed.')
            expect(logic.values.materializeModalSuggestion?.id).toEqual(MATERIALIZE.id)
        }
    )

    it.each<[string, Parameters<typeof logic.actions.setRefreshDraft>[0], Record<string, unknown>]>([
        ['keeps every proposed setting', {}, { refresh_interval_seconds: 86400 }],
        [
            'switches to a full refresh without sending keys the backend would refuse',
            { enabled: false },
            { refresh_interval_seconds: 86400, refresh_mode: 'full' },
        ],
        [
            'sends only the incremental key that changed',
            { incrementalKey: 'created_at' },
            { refresh_interval_seconds: 86400, incremental_key: 'created_at' },
        ],
        [
            'sends a new unique key and lookback',
            { uniqueKey: ['day'], lookbackSeconds: 0 },
            { refresh_interval_seconds: 86400, unique_key: ['day'], lookback_seconds: 0 },
        ],
    ])('materializing an incremental proposal %s', async (_name, change, expectedBody) => {
        mockList.mockResolvedValue(page([INCREMENTAL]))
        mockAccept.mockResolvedValue({ ...INCREMENTAL, status: 'accepted' })
        await mountLogic()
        logic.actions.openMaterializeModal(INCREMENTAL.id)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setRefreshDraft(change)

        logic.actions.confirmMaterialize()

        await expectLogic(logic).toDispatchActions(['suggestionAccepted'])
        expect(mockAccept).toHaveBeenCalledWith(expect.any(String), INCREMENTAL.id, expectedBody)
    })

    it('materializes with a full refresh when the view can no longer refresh incrementally', async () => {
        mockList.mockResolvedValue(page([INCREMENTAL]))
        mockSavedQuery.mockResolvedValue({
            query: { query: 'SELECT * FROM events' },
        } as Awaited<ReturnType<typeof warehouseSavedQueriesRetrieve>>)
        mockCheck.mockResolvedValue({
            eligible: false,
            key_candidates: [],
            unique_key_candidates: [],
            key_candidate_types: {},
            blockers: ['The query has no column that grows over time.'],
            warnings: [],
        })
        mockAccept.mockResolvedValue({ ...INCREMENTAL, status: 'accepted' })
        await mountLogic()
        logic.actions.openMaterializeModal(INCREMENTAL.id)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.confirmMaterialize()
        await expectLogic(logic).toDispatchActions(['suggestionAccepted'])

        expect(mockAccept).toHaveBeenCalledWith(expect.any(String), INCREMENTAL.id, {
            refresh_interval_seconds: 86400,
            refresh_mode: 'full',
        })
    })

    it('switching a full proposal to incremental sends the mode and the keys', async () => {
        mockAccept.mockResolvedValue({ ...MATERIALIZE, status: 'accepted' })
        await mountLogic()
        logic.actions.openMaterializeModal(MATERIALIZE.id)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setRefreshDraft({ enabled: true, incrementalKey: 'day', uniqueKey: ['day'] })

        logic.actions.confirmMaterialize()

        await expectLogic(logic).toDispatchActions(['suggestionAccepted'])
        expect(mockAccept).toHaveBeenCalledWith(expect.any(String), MATERIALIZE.id, {
            refresh_interval_seconds: 86400,
            refresh_mode: 'incremental',
            incremental_key: 'day',
            unique_key: ['day'],
            lookback_seconds: 0,
        })
    })

    it.each<[string, Parameters<typeof logic.actions.setRefreshDraft>[0]]>([
        ['every unique key column is cleared', { uniqueKey: [] }],
        ['the incremental column is cleared', { incrementalKey: null }],
    ])('does not materialize an incremental draft when %s', async (_name, change) => {
        mockList.mockResolvedValue(page([INCREMENTAL]))
        await mountLogic()
        logic.actions.openMaterializeModal(INCREMENTAL.id)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setRefreshDraft(change)
        logic.actions.confirmMaterialize()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.materializeDisabledReason).toEqual('Select the incremental column and unique key columns')
        expect(mockAccept).not.toHaveBeenCalled()
    })

    it('does not materialize while the incremental check is still running', async () => {
        let finishCheck: (
            check: Awaited<ReturnType<typeof warehouseSavedQueriesCheckIncrementalCreate>>
        ) => void = () => {}
        mockSavedQuery.mockResolvedValue({
            query: { query: 'SELECT * FROM events' },
        } as Awaited<ReturnType<typeof warehouseSavedQueriesRetrieve>>)
        mockCheck.mockReturnValue(new Promise((resolve) => (finishCheck = resolve)))
        await mountLogic()
        logic.actions.openMaterializeModal(MATERIALIZE.id)
        await checksRequested(1)

        logic.actions.confirmMaterialize()

        expect(logic.values.materializeDisabledReason).toEqual('Checking whether it can refresh incrementally')
        expect(mockAccept).not.toHaveBeenCalled()
        finishCheck({
            eligible: true,
            key_candidates: ['day'],
            unique_key_candidates: ['day'],
            key_candidate_types: {},
            blockers: [],
            warnings: [],
        })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.materializeDisabledReason).toBeNull()
    })

    it('keeps the open view check when an earlier view check resolves last', async () => {
        const first = materialize('first', 600)
        const second = materialize('second', 1200)
        mockList.mockResolvedValue(page([first, second]))
        mockSavedQuery.mockImplementation(
            async (_project, id) =>
                ({ query: { query: `SELECT * FROM ${id}` } }) as Awaited<
                    ReturnType<typeof warehouseSavedQueriesRetrieve>
                >
        )
        const resolvers: Record<string, (keys: string[]) => void> = {}
        mockCheck.mockImplementation(
            (_project, { query }) =>
                new Promise((resolve) => {
                    resolvers[query] = (keys) =>
                        resolve({
                            eligible: true,
                            key_candidates: keys,
                            unique_key_candidates: keys,
                            key_candidate_types: {},
                            blockers: [],
                            warnings: [],
                        })
                })
        )
        await mountLogic()

        logic.actions.openMaterializeModal(first.id)
        logic.actions.closeMaterializeModal()
        logic.actions.openMaterializeModal(second.id)
        await checksRequested(2)
        resolvers[`SELECT * FROM ${second.subject_id}`](['second_day'])
        resolvers[`SELECT * FROM ${first.subject_id}`](['first_day'])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.incrementalCheck?.key_candidates).toEqual(['second_day'])
        expect(logic.values.refreshDraft.incrementalKey).toEqual('second_day')
    })

    it('checks the view for incremental refresh when the dialog opens', async () => {
        mockSavedQuery.mockResolvedValue({
            query: { query: 'SELECT day, plan, count() FROM events GROUP BY day, plan' },
        } as Awaited<ReturnType<typeof warehouseSavedQueriesRetrieve>>)
        mockCheck.mockResolvedValue({
            eligible: true,
            key_candidates: ['day'],
            unique_key_candidates: ['day', 'plan'],
            key_candidate_types: { day: 'date' },
            blockers: [],
            warnings: [],
        })
        await mountLogic()

        logic.actions.openMaterializeModal(MATERIALIZE.id)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockCheck).toHaveBeenCalledTimes(1)
        expect(logic.values.incrementalCheck?.key_candidates).toEqual(['day'])
    })

    it.each<[SuggestionSurface, WarehouseSuggestionApi[], string[]]>([
        [
            'models',
            [
                materialize('bytes-big', 0, 5e12),
                materialize('time-small', 600),
                unmaterialize('unread-mid', 3000, 1500),
                materialize('time-big', 2400),
            ],
            ['time-big', 'unread-mid', 'time-small', 'bytes-big'],
        ],
        ['catalog', [certification('old', 'deprecate'), certification('used', 'certify')], ['used', 'old']],
    ])('orders %s suggestions by what they are worth', async (surface, results, expectedOrder) => {
        mockList.mockResolvedValue(page(results))

        await mountLogic(surface)

        expect(logic.values.surfaceSuggestions.map((suggestion) => suggestion.id)).toEqual(expectedOrder)
    })

    it('sums time and bytes across every view, including views that save both', async () => {
        mockList.mockResolvedValue(
            page([materialize('a', 1800, 2e12), materialize('b', 1200), materialize('c', 0, 3e12)])
        )

        await mountLogic()

        expect(logic.values.savingsSummary).toEqual({ views: 3, saving: { seconds: 3000, bytes: 5e12 } })
    })

    it('drops an accepted row from the counts at once and from the list after it leaves', async () => {
        jest.useFakeTimers()
        try {
            mockList.mockResolvedValue(page([materialize('a', 1800), materialize('b', 1200)]))
            mockAccept.mockResolvedValue({ ...materialize('a', 1800), status: 'accepted' })
            await mountLogic()

            logic.actions.acceptSuggestion('a', { refresh_interval_seconds: 86400 })
            await expectLogic(logic).toDispatchActions(['suggestionAccepted'])

            expect(logic.values.savingsSummary.saving.seconds).toEqual(1200)
            expect(logic.values.listedSuggestions.map((suggestion) => suggestion.id)).toEqual(['a', 'b'])

            jest.advanceTimersByTime(ROW_LEAVE_MS)

            expect(logic.values.listedSuggestions.map((suggestion) => suggestion.id)).toEqual(['b'])
        } finally {
            jest.useRealTimers()
        }
    })

    it('stays mounted as all done while the last row leaves and after it is gone', async () => {
        jest.useFakeTimers()
        try {
            mockAccept.mockResolvedValue({ ...MATERIALIZE, status: 'accepted' })
            await mountLogic()

            logic.actions.acceptSuggestion(MATERIALIZE.id, { refresh_interval_seconds: 86400 })
            await expectLogic(logic).toDispatchActions(['suggestionAccepted'])
            expect(logic.values.stripState).toEqual('all_done')

            jest.advanceTimersByTime(ROW_LEAVE_MS)
            expect(logic.values.stripState).toEqual('all_done')
        } finally {
            jest.useRealTimers()
        }
    })

    it('keeps a row whose dismiss failed even after its leave timer would have fired', async () => {
        jest.useFakeTimers()
        try {
            mockDismiss.mockRejectedValue(new Error('network'))
            await mountLogic()

            logic.actions.dismissSuggestion(MATERIALIZE.id, 'not_useful')
            await expectLogic(logic).toDispatchActions(['restoreSuggestion'])
            jest.advanceTimersByTime(ROW_LEAVE_MS)

            expect(logic.values.surfaceSuggestions.map((suggestion) => suggestion.id)).toEqual([MATERIALIZE.id])
        } finally {
            jest.useRealTimers()
        }
    })

    it('gives each dismiss its own toast so every Undo stays reachable', async () => {
        mockList.mockResolvedValue(page([materialize('a', 600), materialize('b', 600)]))
        mockDismiss.mockImplementation(async (_project, id) => ({ ...materialize(id, 600), status: 'dismissed' }))
        await mountLogic()

        logic.actions.dismissSuggestion('a', 'not_useful')
        logic.actions.dismissSuggestion('b', 'not_useful')
        await expectLogic(logic).toFinishAllListeners()

        const toastIds = (lemonToast.success as jest.Mock).mock.calls.map(([, options]) => options.toastId)
        expect(new Set(toastIds).size).toEqual(2)
    })

    it('brings a dismissed row back through resume even after the list reloaded without it', async () => {
        mockDismiss.mockResolvedValue({ ...MATERIALIZE, status: 'dismissed' })
        mockResume.mockResolvedValue({ ...MATERIALIZE, status: 'proposed' })
        await mountLogic()
        logic.actions.dismissSuggestion(MATERIALIZE.id, 'not_now')
        await expectLogic(logic).toFinishAllListeners()
        mockList.mockResolvedValue(page([]))
        logic.actions.loadSuggestions()
        await expectLogic(logic).toDispatchActions(['loadSuggestionsSuccess'])

        logic.actions.undoDismiss(MATERIALIZE.id)

        await expectLogic(logic).toDispatchActions(['suggestionResumed', 'restoreSuggestion'])
        expect(mockResume).toHaveBeenCalledWith(expect.any(String), MATERIALIZE.id)
        expect(logic.values.surfaceSuggestions.map((suggestion) => suggestion.id)).toEqual([MATERIALIZE.id])
    })

    it('brings a dismissed row back through the toast Undo even after the logic unmounted', async () => {
        mockDismiss.mockResolvedValue({ ...MATERIALIZE, status: 'dismissed' })
        mockResume.mockResolvedValue({ ...MATERIALIZE, status: 'proposed' })
        await mountLogic()
        logic.actions.dismissSuggestion(MATERIALIZE.id, 'not_now')
        await expectLogic(logic).toFinishAllListeners()
        const [message, options] = (lemonToast.success as jest.Mock).mock.calls[0]
        logic.unmount()

        options.button.action()
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(message).toEqual('Dismissed. Suggested again if it would save a lot more.')
        expect(mockResume).toHaveBeenCalledWith(expect.any(String), MATERIALIZE.id)
    })

    it('keeps the row hidden when undo fails', async () => {
        mockDismiss.mockResolvedValue({ ...MATERIALIZE, status: 'dismissed' })
        mockResume.mockRejectedValue(new Error('network'))
        await mountLogic()
        logic.actions.dismissSuggestion(MATERIALIZE.id, 'not_now')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.undoDismiss(MATERIALIZE.id)
        await expectLogic(logic).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.surfaceSuggestions).toEqual([])
    })

    it('offers no catalog View while the certification it would point at does not exist yet', async () => {
        const accepted = certification('used', 'certify')
        mockList.mockResolvedValue(page([accepted]))
        mockAccept.mockResolvedValue({ ...accepted, status: 'accepted', created_asset: null })
        await mountLogic('catalog', jest.fn())

        logic.actions.acceptSuggestion(accepted.id)
        await expectLogic(logic).toDispatchActions(['suggestionAccepted'])

        expect((lemonToast.success as jest.Mock).mock.calls[0][1].button).toBeUndefined()
    })

    async function acceptAndClickView(
        surface: SuggestionSurface,
        accepted: WarehouseSuggestionApi,
        onViewAccepted?: (suggestion: WarehouseSuggestionApi) => void
    ): Promise<void> {
        mockList.mockResolvedValue(page([accepted]))
        mockAccept.mockResolvedValue({ ...accepted, status: 'accepted' })
        await mountLogic(surface, onViewAccepted)
        logic.actions.openReview()
        logic.actions.acceptSuggestion(accepted.id)
        await expectLogic(logic).toDispatchActions(['suggestionAccepted'])
        const [, options] = (lemonToast.success as jest.Mock).mock.calls[0]
        options.button.action()
    }

    it.each([MATERIALIZE, unmaterialize('unread', 3000, 1500)])(
        'sends the strip toast View for $kind to the materialization tab of its model page',
        async (accepted) => {
            await acceptAndClickView('models', accepted)

            expect(router.values.location.pathname + router.values.location.search).toContain(
                `${urls.nodeDetail(accepted.subject_id, 'materialization')}?lookup=saved_query`
            )
        }
    )

    it.each<[string, boolean, Record<string, unknown> | undefined, string]>([
        ['stops refreshing by default', false, undefined, 'Marked old_rollup as deprecated and stopped its refreshes.'],
        ['keeps refreshing when asked', true, { keep_materialized: true }, 'Marked old_rollup as deprecated.'],
    ])('deprecating a materialized view %s', async (_name, keep, body, toast) => {
        mockList.mockResolvedValue(page([DEPRECATE]))
        mockAccept.mockResolvedValue({
            ...DEPRECATE,
            status: 'accepted',
            created_asset: { certification_id: 'cert-1', stopped_materialization: !keep },
        })
        await mountLogic('catalog')
        logic.actions.openAcceptConfirm(DEPRECATE.id)
        logic.actions.setKeepMaterialized(keep)

        logic.actions.confirmAccept()
        await expectLogic(logic).toDispatchActions(['suggestionAccepted'])

        expect(mockAccept).toHaveBeenCalledWith(expect.any(String), DEPRECATE.id, body)
        expect((lemonToast.success as jest.Mock).mock.calls[0][0]).toEqual(toast)
        expect(logic.values.acceptConfirmSuggestion).toBeNull()
    })

    it('reloads the list when an accept finds the view or table deleted', async () => {
        mockAccept.mockRejectedValue(new ApiError('Not found.', 404, undefined, { detail: 'Not found.' }))
        await mountLogic()

        logic.actions.acceptSuggestion(MATERIALIZE.id, { refresh_interval_seconds: 86400 })

        await expectLogic(logic).toDispatchActions(['loadSuggestions', 'loadSuggestionsSuccess'])
        expect(lemonToast.error).toHaveBeenCalledWith(
            'This suggestion is gone, or its view or table was deleted. The list is up to date now.'
        )
    })

    it('shows why the backend refused to stop materializing, closes the dialog and reloads', async () => {
        const unread = unmaterialize('unread', 3000, 1500)
        mockList.mockResolvedValue(page([unread]))
        mockAccept.mockRejectedValue(
            new ApiError('conflict', 409, undefined, { detail: 'Another view reads this view now.' })
        )
        await mountLogic()
        logic.actions.openAcceptConfirm(unread.id)

        logic.actions.confirmAccept()

        await expectLogic(logic).toDispatchActions(['acceptSuggestionFailed', 'loadSuggestions'])
        expect(lemonToast.error).toHaveBeenCalledWith('Another view reads this view now.')
        expect(logic.values.acceptConfirmSuggestion).toBeNull()
    })

    it('hands the catalog toast View to the host so it can show the new certification', async () => {
        const onViewAccepted = jest.fn()
        const accepted = { ...certification('used', 'certify'), created_asset: { certification_id: 'cert-1' } }

        await acceptAndClickView('catalog', accepted, onViewAccepted)

        expect(onViewAccepted).toHaveBeenCalledWith(expect.objectContaining({ id: accepted.id }))
        expect(logic.values.reviewOpen).toBe(false)
    })

    it.each<[string, number, boolean]>([
        ['shorter than suggested', 3600, true],
        ['the suggested one', 86400, false],
        ['longer than suggested', 7 * 86400, false],
    ])('warns about a picked schedule %s only when it is shorter', async (_name, pickedSeconds, warns) => {
        await mountLogic()
        logic.actions.openMaterializeModal(MATERIALIZE.id)

        logic.actions.setMaterializeInterval(intervalForSeconds(pickedSeconds))

        expect(logic.values.materializeIntervalShorterThanSuggested).toEqual(warns)
    })
})
