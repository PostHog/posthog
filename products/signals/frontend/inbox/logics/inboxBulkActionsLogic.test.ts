/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    SignalReportBulkStateRequestApi,
    SignalReportBulkStateResponseApi,
} from 'products/signals/frontend/generated/api.schemas'

import { inboxBulkActionsLogic } from './inboxBulkActionsLogic'

const BULK_STATE_URL = '/api/projects/:team_id/signals/reports/bulk-state/'

const bulkStateResponse = (
    overrides: Partial<SignalReportBulkStateResponseApi> = {}
): SignalReportBulkStateResponseApi => ({
    results: [],
    transitioned_count: 0,
    skipped_count: 0,
    failed_count: 0,
    not_found_count: 0,
    ...overrides,
})

describe('inboxBulkActionsLogic', () => {
    let logic: ReturnType<typeof inboxBulkActionsLogic.build>
    let requests: SignalReportBulkStateRequestApi[]

    const mockBulkState = (
        respond: (body: SignalReportBulkStateRequestApi) => SignalReportBulkStateResponseApi = (body) =>
            bulkStateResponse({ transitioned_count: body.ids.length })
    ): void => {
        useMocks({
            post: {
                [BULK_STATE_URL]: async ({ request }) => {
                    const body = (await request.json()) as SignalReportBulkStateRequestApi
                    requests.push(body)
                    return [200, respond(body)]
                },
            },
        })
    }

    beforeEach(() => {
        initKeaTests()
        requests = []
        logic = inboxBulkActionsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('dismisses the whole selection in one request rather than one per report', async () => {
        mockBulkState()
        logic.actions.setSelectedReportIds(['report-a', 'report-b', 'report-c'])

        await expectLogic(logic, () => {
            logic.actions.bulkDismiss('report_unclear', '  needs more detail  ')
        }).toFinishAllListeners()

        expect(requests).toHaveLength(1)
        expect(requests[0]).toEqual({
            ids: ['report-a', 'report-b', 'report-c'],
            state: 'suppressed',
            dismissal_reason: 'report_unclear',
            dismissal_note: 'needs more detail',
        })
    })

    it('omits the note when the user typed nothing', async () => {
        mockBulkState()
        logic.actions.setSelectedReportIds(['report-a'])

        await expectLogic(logic, () => {
            logic.actions.bulkDismiss('wontfix_irrelevant', '   ')
        }).toFinishAllListeners()

        expect(requests[0]).not.toHaveProperty('dismissal_note')
    })

    it('splits a selection larger than the endpoint limit into batches', async () => {
        mockBulkState()
        const reportIds = Array.from({ length: 150 }, (_, index) => `report-${index}`)
        logic.actions.setSelectedReportIds(reportIds)

        await expectLogic(logic, () => {
            logic.actions.bulkDismiss('other', '')
        }).toFinishAllListeners()

        expect(requests.map((request) => request.ids.length)).toEqual([100, 50])
        expect(requests.flatMap((request) => request.ids)).toEqual(reportIds)
    })

    it('treats a 200 that transitioned nothing as a failure', async () => {
        mockBulkState((body) => bulkStateResponse({ skipped_count: body.ids.length }))
        logic.actions.setSelectedReportIds(['report-a', 'report-b'])

        await expectLogic(logic, () => {
            logic.actions.bulkDismiss('already_fixed', '')
        }).toDispatchActions(['bulkDismissFailure'])

        expect(logic.values.isDismissing).toBe(false)
    })

    it('treats a partially skipped batch as a success so the list reloads', async () => {
        mockBulkState(() => bulkStateResponse({ transitioned_count: 1, skipped_count: 1 }))
        logic.actions.setSelectedReportIds(['report-a', 'report-b'])

        await expectLogic(logic, () => {
            logic.actions.bulkDismiss('analysis_wrong', '')
        }).toDispatchActions(['bulkDismissSuccess'])

        expect(logic.values.selectedReportIds).toEqual([])
    })
})
