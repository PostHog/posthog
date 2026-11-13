import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import {
    warehouseSuggestionsAcceptCreate,
    warehouseSuggestionsList,
    warehouseSuggestionsStatusRetrieve,
} from './generated/api'
import type { WarehouseSuggestionApi, WarehouseSuggestionStatusApi } from './generated/api.schemas'
import { warehouseSuggestionsLogic } from './warehouseSuggestionsLogic'
import { SuggestionsSectionFilters, warehouseSuggestionsSectionLogic } from './warehouseSuggestionsSectionLogic'

jest.mock('lib/utils/accessControlUtils', () => ({ userHasAccess: jest.fn(() => true) }))
jest.mock('./generated/api', () => ({
    warehouseSuggestionsAcceptCreate: jest.fn(),
    warehouseSuggestionsAssignCreate: jest.fn(),
    warehouseSuggestionsDismissCreate: jest.fn(),
    warehouseSuggestionsList: jest.fn(),
    warehouseSuggestionsStatusRetrieve: jest.fn(),
}))

const mockList = jest.mocked(warehouseSuggestionsList)
const mockStatus = jest.mocked(warehouseSuggestionsStatusRetrieve)
const mockAccept = jest.mocked(warehouseSuggestionsAcceptCreate)

const STATUS: WarehouseSuggestionStatusApi = {
    enabled: true,
    eligible: true,
    days_with_data: 30,
    window_days: 30,
    paused_reason: null,
    refreshed_at: '2026-10-07T08:30:00Z',
    waiting: 0,
    can_show_more: false,
}

const CURRENT_USER_ID = MOCK_DEFAULT_USER.id

function suggestion(
    id: string,
    kind: WarehouseSuggestionApi['kind'],
    subjectKind: 'table' | 'saved_query',
    payload: Record<string, unknown> = {},
    assigneeId?: number
): WarehouseSuggestionApi {
    return {
        id,
        kind,
        subject_kind: subjectKind,
        subject_id: `subject-${id}`,
        payload: { subject_name: id, ...payload } as WarehouseSuggestionApi['payload'],
        payload_version: 1,
        evidence: {},
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
        assignee: assigneeId ? { ...MOCK_DEFAULT_USER, id: assigneeId } : null,
    }
}

const MATERIALIZE = suggestion('orders_daily', 'materialize', 'saved_query', {
    refresh_interval_seconds: 86400,
    saves_seconds_per_month: 1200,
    saves_bytes_per_month: 0,
})
const CERTIFY = suggestion('stripe_charges', 'certify', 'table', {}, CURRENT_USER_ID)
const DEPRECATE_VIEW = suggestion('old_rollup', 'deprecate', 'saved_query', {
    refresh_seconds_per_month: 5400,
    refresh_bytes_per_month: 0,
})
const ALL = [MATERIALIZE, CERTIFY, DEPRECATE_VIEW]

describe('warehouseSuggestionsSectionLogic', () => {
    let logic: ReturnType<typeof warehouseSuggestionsSectionLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.clearAllMocks()
        jest.spyOn(lemonToast, 'success').mockImplementation(() => 'toast')
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')
        mockStatus.mockResolvedValue(STATUS)
        mockList.mockResolvedValue({ count: ALL.length, results: ALL } as Awaited<
            ReturnType<typeof warehouseSuggestionsList>
        >)
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        logic = warehouseSuggestionsSectionLogic({})
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ filteredGroups: expect.arrayContaining([expect.anything()]) })
    })

    afterEach(() => logic.unmount())

    it.each<[string, Partial<SuggestionsSectionFilters>, string[]]>([
        ['kind', { kind: 'certify' }, [CERTIFY.id]],
        ['assigned to me', { assignee: 'me' }, [CERTIFY.id]],
        ['unassigned', { assignee: 'unassigned' }, [MATERIALIZE.id, DEPRECATE_VIEW.id]],
        ['views only', { subject: 'views' }, [MATERIALIZE.id, DEPRECATE_VIEW.id]],
        ['name search', { search: 'ROLL' }, [DEPRECATE_VIEW.id]],
    ])('narrows the groups by %s', (_name, filters, expectedIds) => {
        logic.actions.setFilters(filters)

        expect(logic.values.filteredGroups.flatMap((group) => group.suggestions.map(({ id }) => id))).toEqual(
            expectedIds
        )
    })

    it.each<[string, Parameters<typeof logic.actions.setAcceptChoices>[0], Record<string, unknown>]>([
        ['each view keeps its suggested interval', {}, { refresh_interval_seconds: 86400 }],
        [
            'one interval applies to every view',
            { intervalChoice: 'fixed', interval: '1hour' },
            { refresh_interval_seconds: 3600 },
        ],
    ])('bulk approve sends the chosen options when %s', async (_name, choices, materializeBody) => {
        mockAccept.mockImplementation(async (_project, id) => ({
            ...ALL.find((item) => item.id === id)!,
            status: 'accepted',
        }))
        logic.actions.setSelected(
            ALL.map(({ id }) => id),
            true
        )
        logic.actions.openBulkAccept()
        logic.actions.setAcceptChoices({ ...choices, deleteViews: false, keepMaterialized: true })

        logic.actions.confirmBulkAccept()
        await expectLogic(logic).toDispatchActions(['setBulkActionRunning', 'setBulkActionRunning'])

        expect(mockAccept.mock.calls.map(([, id, body]) => [id, body])).toEqual([
            [MATERIALIZE.id, materializeBody],
            [CERTIFY.id, undefined],
            [DEPRECATE_VIEW.id, { keep_materialized: true }],
        ])
        expect(lemonToast.success).toHaveBeenCalledWith('Approved 3 suggestions.')
    })

    it('reserves every queued row before the first request returns and skips a row already being saved', async () => {
        let finishFirst: () => void = () => {}
        const firstReturns = new Promise<void>((resolve) => (finishFirst = resolve))
        mockAccept.mockImplementation(async (_project, id) => {
            if (id === MATERIALIZE.id) {
                await firstReturns
            }
            return { ...ALL.find((item) => item.id === id)!, status: 'accepted' }
        })
        const mainLogic = warehouseSuggestionsLogic({})
        mainLogic.actions.setActionInFlight(CERTIFY.id, true)
        logic.actions.setSelected(
            ALL.map(({ id }) => id),
            true
        )

        logic.actions.confirmBulkAccept()

        expect(mainLogic.values.actionsInFlight[DEPRECATE_VIEW.id]).toBe(true)
        finishFirst()
        await expectLogic(logic).toDispatchActions(['setBulkActionRunning', 'setBulkActionRunning'])
        expect(mockAccept.mock.calls.map(([, id]) => id)).toEqual([MATERIALIZE.id, DEPRECATE_VIEW.id])
    })

    it('keeps the failed rows selected and names the failure in one toast', async () => {
        mockAccept.mockImplementation(async (_project, id) => {
            if (id === CERTIFY.id) {
                throw new ApiError('denied', 403, undefined, { detail: 'You need edit access.' })
            }
            return { ...ALL.find((item) => item.id === id)!, status: 'accepted' }
        })
        logic.actions.setSelected(
            ALL.map(({ id }) => id),
            true
        )

        logic.actions.confirmBulkAccept()
        await expectLogic(logic).toDispatchActions(['setBulkActionRunning', 'setBulkActionRunning'])

        expect(logic.values.selectedIds).toEqual([CERTIFY.id])
        expect(lemonToast.error).toHaveBeenCalledWith('Approved 2 suggestions. 1 failed: You need edit access.')
    })
})
