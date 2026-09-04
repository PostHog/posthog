import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { hogFunctionsPartialUpdate, hogFunctionsRetrieve } from 'products/cdp/frontend/generated/api'
import { signalsScoutConfigDestroy } from 'products/signals/frontend/generated/api'
import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import { scoutFleetLogic } from 'products/signals/frontend/inbox/logics/scoutFleetLogic'

import {
    visionScannersScoutReportsList,
    visionScannersScoutReportsRetrieve,
    visionScannersScoutsCreate,
} from '../generated/api'
import type { ScoutReportApi } from '../generated/api.schemas'
import { scannerScoutLogic } from './scannerScoutLogic'

jest.mock('posthog-js')
jest.mock('products/replay_vision/frontend/generated/api')
jest.mock('products/signals/frontend/generated/api')
jest.mock('products/skills/frontend/generated/api')
jest.mock('products/cdp/frontend/generated/api')

const mockReportsList = visionScannersScoutReportsList as jest.MockedFunction<typeof visionScannersScoutReportsList>
const mockReportRetrieve = visionScannersScoutReportsRetrieve as jest.MockedFunction<
    typeof visionScannersScoutReportsRetrieve
>
const mockScoutConfigDestroy = signalsScoutConfigDestroy as jest.MockedFunction<typeof signalsScoutConfigDestroy>
const mockScoutsCreate = visionScannersScoutsCreate as jest.MockedFunction<typeof visionScannersScoutsCreate>
const mockHogFunctionsRetrieve = hogFunctionsRetrieve as jest.MockedFunction<typeof hogFunctionsRetrieve>
const mockHogFunctionsPartialUpdate = hogFunctionsPartialUpdate as jest.MockedFunction<typeof hogFunctionsPartialUpdate>

const SCANNER_ID = '01a014ea-854f-72b5-8192-bb6ac9f212a5'
const SKILL_NAME = 'signals-scout-daily-digest'
const WEBHOOK_ID = 'hog-1'

function makeReport(overrides: Partial<ScoutReportApi> = {}): ScoutReportApi {
    return {
        report_id: 'report-1',
        skill_name: SKILL_NAME,
        filed_at: '2026-08-20T09:00:00Z',
        title: 'Rage clicks held steady',
        summary: 'Nothing notable this week.',
        charts: [],
        ...overrides,
    }
}

function makeConfig(overrides: Partial<SignalScoutConfigApi> = {}): SignalScoutConfigApi {
    return {
        id: 'config-1',
        skill_name: SKILL_NAME,
        description: 'Daily digest for this scanner.',
        scout_origin: 'custom',
        enabled: true,
        status: 'active',
        pause_reason: null,
        emit: true,
        run_interval_minutes: 1440,
        run_cron_schedule: '0 9 * * *',
        output_destinations: { webhook: { hog_function_id: WEBHOOK_ID } },
        structured_output_schema: null,
        mcp_gateway_server_ids: [],
        last_run_at: null,
        consecutive_failure_count: 0,
        status_changed_at: null,
        auto_pause_exempt: false,
        network_access: 'trusted',
        model: null,
        source_product: 'replay_vision',
        source_id: SCANNER_ID,
        created_at: '2026-08-01T00:00:00Z',
        ...overrides,
    } as SignalScoutConfigApi
}

describe('scannerScoutLogic', () => {
    let logic: ReturnType<typeof scannerScoutLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockReportsList.mockResolvedValue([])
    })

    afterEach(() => {
        logic?.unmount()
    })

    async function mountWithReports(reports: ScoutReportApi[]): Promise<void> {
        mockReportsList.mockResolvedValue(reports)
        logic = scannerScoutLogic({ scannerId: SCANNER_ID, scannerName: 'Rage clicks on checkout' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('resolves the latest report without waiting for the scout roster', async () => {
        // The card reads `latestReportRow` on a cold load, before the fleet logic has answered with
        // this scanner's configs. Deriving reports from the fleet's runs window instead of this
        // scanner-scoped request leaves the card claiming nothing was reported until the roster lands.
        await mountWithReports([makeReport({ report_id: 'newest' }), makeReport({ report_id: 'older' })])

        expect(mockReportsList).toHaveBeenCalledWith(expect.any(String), SCANNER_ID)
        expect(logic.values.scoutConfigs).toBeFalsy()
        expect(logic.values.latestReportRow?.report_id).toBe('newest')
    })

    it('has no report to show while the request is still in flight', async () => {
        // "Nothing reported yet" is a verdict about reports that arrived. Anything that lets the
        // logic present an unresolved fetch as an answered one puts that verdict on every cold load.
        let resolveReports: (reports: ScoutReportApi[]) => void = () => {}
        mockReportsList.mockReturnValue(new Promise((resolve) => (resolveReports = resolve)))
        logic = scannerScoutLogic({ scannerId: SCANNER_ID, scannerName: 'Rage clicks on checkout' })
        logic.mount()

        expect(logic.values.scoutReportsLoading).toBe(true)
        expect(logic.values.latestReportRow).toBeNull()

        resolveReports([makeReport()])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scoutReportsLoading).toBe(false)
        expect(logic.values.latestReportRow?.report_id).toBe('report-1')
    })

    it('opens a report the list already carries without fetching it again', async () => {
        // The list carries the whole report. A per-report GET here is wasted, and the endpoint it
        // would call is the one that enforces this scanner's read boundary.
        await mountWithReports([makeReport()])

        logic.actions.openReport('report-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockReportRetrieve).not.toHaveBeenCalled()
        expect(logic.values.openedReport?.report_id).toBe('report-1')
    })

    it('fetches a report the list does not carry', async () => {
        await mountWithReports([makeReport()])
        mockReportRetrieve.mockResolvedValue(makeReport({ report_id: 'from-another-page' }))

        logic.actions.openReport('from-another-page')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockReportRetrieve).toHaveBeenCalledWith(expect.any(String), SCANNER_ID, 'from-another-page')
        expect(logic.values.openedReport?.report_id).toBe('from-another-page')
    })

    it('retires the scout webhook only once the delete is confirmed', async () => {
        // The fleet fires `deleteScoutFinished` from a `finally`, so a failed delete fires it too.
        // Retiring the destination there kills delivery for a scout that still exists.
        await mountWithReports([])
        mockHogFunctionsRetrieve.mockResolvedValue({
            id: WEBHOOK_ID,
            name: 'Replay Vision · Rage clicks on checkout',
            deleted: false,
            template: { id: 'template-webhook' },
            filters: {
                events: [{ id: '$scout_report_emitted' }],
                properties: [{ key: 'skill_name', value: SKILL_NAME }],
            },
            inputs: {},
        } as any)
        const fleet = scoutFleetLogic.findMounted()!

        fleet.actions.loadScoutConfigsSuccess([makeConfig()])
        mockScoutConfigDestroy.mockRejectedValueOnce(new Error('nope'))
        fleet.actions.deleteScout('config-1', 'replay_vision_scanner')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockHogFunctionsPartialUpdate).not.toHaveBeenCalled()

        fleet.actions.loadScoutConfigsSuccess([makeConfig()])
        mockScoutConfigDestroy.mockResolvedValueOnce(undefined as never)
        fleet.actions.deleteScout('config-1', 'replay_vision_scanner')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockHogFunctionsPartialUpdate).toHaveBeenCalledWith(expect.any(String), WEBHOOK_ID, {
            enabled: false,
            deleted: true,
        })
    })

    it('renames and retries when another tab already took the name', async () => {
        // Skill names are unique per team, so a scout created in one tab leaves this tab's roster
        // stale and its derived name already taken.
        await mountWithReports([])
        mockScoutsCreate
            .mockRejectedValueOnce(Object.assign(new Error('conflict'), { status: 409 }))
            .mockResolvedValueOnce({ created: true, config: makeConfig() } as any)

        logic.actions.createScout({
            name: 'Daily digest',
            body: 'Watch this scanner.',
            cron: '0 9 * * *',
            outputDestinations: {},
            webhookUrl: '',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockScoutsCreate).toHaveBeenCalledTimes(2)
        const [firstName, secondName] = mockScoutsCreate.mock.calls.map((call) => (call[2] as any).name)
        expect(firstName).toBe('signals-scout-rage-clicks-on-checkout-daily-digest')
        expect(secondName).toBe('signals-scout-rage-clicks-on-checkout-daily-digest-2')
    })

    it('separates a failed report load from a scout that filed nothing', async () => {
        // Both leave the list empty. Reading a failure as "filed nothing" offers Run now, and that
        // click spends credits on a scout whose reports may already exist.
        mockReportsList.mockRejectedValueOnce(new Error('boom'))
        logic = scannerScoutLogic({ scannerId: SCANNER_ID, scannerName: 'Rage clicks on checkout' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scoutReports).toEqual([])
        expect(logic.values.scoutReportsFailed).toBe(true)

        mockReportsList.mockResolvedValueOnce([makeReport()])
        logic.actions.loadScoutReports()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scoutReportsFailed).toBe(false)
    })
})
