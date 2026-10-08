import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import {
    warehouseSuggestionsAcceptCreate,
    warehouseSuggestionsDismissCreate,
    warehouseSuggestionsList,
    warehouseSuggestionsStatusRetrieve,
} from './generated/api'
import type { WarehouseSuggestionApi, WarehouseSuggestionStatusApi } from './generated/api.schemas'
import { StripState, warehouseSuggestionsLogic } from './warehouseSuggestionsLogic'

jest.mock('./generated/api', () => ({
    warehouseSuggestionsAcceptCreate: jest.fn(),
    warehouseSuggestionsDismissCreate: jest.fn(),
    warehouseSuggestionsList: jest.fn(),
    warehouseSuggestionsStatusRetrieve: jest.fn(),
}))

const mockList = warehouseSuggestionsList as jest.MockedFunction<typeof warehouseSuggestionsList>
const mockStatus = warehouseSuggestionsStatusRetrieve as jest.MockedFunction<typeof warehouseSuggestionsStatusRetrieve>
const mockAccept = warehouseSuggestionsAcceptCreate as jest.MockedFunction<typeof warehouseSuggestionsAcceptCreate>
const mockDismiss = warehouseSuggestionsDismissCreate as jest.MockedFunction<typeof warehouseSuggestionsDismissCreate>

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
    },
    payload_version: 1,
    evidence: { human_requests: 200, human_users: 6, human_days: 25 },
    evidence_window_start: '2026-09-07T00:00:00Z',
    evidence_window_end: '2026-10-07T00:00:00Z',
    last_seen_at: '2026-10-07T08:30:00Z',
    score: 2,
    status: 'proposed',
    surfaced_at: '2026-10-07T08:30:00Z',
    reviewed_by: null,
    reviewed_at: null,
    dismissal_reason: null,
    dismissal_note: null,
    created_asset: null,
    asset_outcome: null,
    can_act: true,
}

function page(results: WarehouseSuggestionApi[]): Awaited<ReturnType<typeof warehouseSuggestionsList>> {
    return { count: results.length, results } as Awaited<ReturnType<typeof warehouseSuggestionsList>>
}

describe('warehouseSuggestionsLogic', () => {
    let logic: ReturnType<typeof warehouseSuggestionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')
        jest.spyOn(lemonToast, 'success').mockImplementation(() => 'toast')
        mockStatus.mockResolvedValue(ACTIVE_STATUS)
        mockList.mockResolvedValue(page([MATERIALIZE]))
    })

    afterEach(() => logic?.unmount())

    async function mountLogic(): Promise<void> {
        logic = warehouseSuggestionsLogic({ surface: 'models' })
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

    it('shows the error state when the status request fails, and retry loads both again', async () => {
        mockStatus.mockRejectedValueOnce(new Error('status is down'))
        logic = warehouseSuggestionsLogic({ surface: 'models' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadStatusFailure'])
        expect(logic.values.stripState).toEqual('error')

        logic.actions.reload()

        await expectLogic(logic).toDispatchActions(['loadSuggestionsSuccess', 'loadStatusSuccess'])
        expect(logic.values.stripState).toEqual('active')
    })

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

        logic.actions.acceptSuggestion(MATERIALIZE.id, 86400)
        logic.actions.acceptSuggestion(MATERIALIZE.id, 86400)
        finish({ ...MATERIALIZE, status: 'accepted' })
        await expectLogic(logic).toDispatchActions(['suggestionAccepted'])

        expect(mockAccept).toHaveBeenCalledTimes(1)
        expect(logic.values.surfaceSuggestions).toEqual([])
    })

    it('restores a dismissed card and reloads when someone else decided it first', async () => {
        mockDismiss.mockRejectedValue(new ApiError('conflict', 409, undefined, { detail: 'already decided' }))
        await mountLogic()

        logic.actions.dismissSuggestion(MATERIALIZE.id, 'not_now')

        await expectLogic(logic).toDispatchActions(['restoreSuggestion', 'loadSuggestions', 'loadSuggestionsSuccess'])
        expect(logic.values.surfaceSuggestions.map((suggestion) => suggestion.id)).toEqual([MATERIALIZE.id])
    })

    it('keeps the materialize modal open with the error when the schedule is refused', async () => {
        mockAccept.mockRejectedValue(
            new ApiError('refused', 400, undefined, {
                detail: 'A source refreshes daily.',
                attr: 'refresh_interval_seconds',
            })
        )
        await mountLogic()
        logic.actions.openMaterializeModal(MATERIALIZE.id)

        logic.actions.acceptSuggestion(MATERIALIZE.id, 3600)

        await expectLogic(logic).toDispatchActions(['setMaterializeError'])
        expect(logic.values.materializeError).toEqual('A source refreshes daily.')
        expect(logic.values.materializeModalSuggestion?.id).toEqual(MATERIALIZE.id)
    })
})
