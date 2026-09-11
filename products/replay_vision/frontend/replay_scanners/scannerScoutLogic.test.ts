import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { hogFunctionsPartialUpdate, hogFunctionsRetrieve } from 'products/cdp/frontend/generated/api'
import { signalsScoutConfigDestroy, signalsScoutConfigUpdate } from 'products/signals/frontend/generated/api'
import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import { scoutFleetLogic } from 'products/signals/frontend/inbox/logics/scoutFleetLogic'
import { llmSkillsNamePartialUpdate } from 'products/skills/frontend/generated/api'

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

    it('saves the display name without changing the skill or delivery', async () => {
        await mountWithReports([])
        const config = makeConfig({ output_destinations: {} })
        scoutFleetLogic.findMounted()!.actions.loadScoutConfigsSuccess([config])
        logic.actions.openScoutSettings(SKILL_NAME)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadSkillPromptSuccess({ skillName: SKILL_NAME, body: 'Watch this scanner.' })
        jest.mocked(signalsScoutConfigUpdate).mockResolvedValue({ ...config, display_name: 'Checkout / daily digest' })

        logic.actions.saveScoutSettings({
            name: '  Checkout / daily digest  ',
            body: 'Watch this scanner.',
            cron: config.run_cron_schedule!,
            outputDestinations: {},
            webhookUrl: '',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(signalsScoutConfigUpdate).toHaveBeenCalledWith(expect.any(String), config.id, {
            display_name: 'Checkout / daily digest',
        })
        expect(llmSkillsNamePartialUpdate).not.toHaveBeenCalled()
        expect(mockHogFunctionsPartialUpdate).not.toHaveBeenCalled()
        expect(logic.values.settingsSkillName).toBeNull()
    })

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

    it('keeps the whole typed name on a scout whose skill name had to be shortened', async () => {
        // The name field is not bounded by the skill name: the typed name is recorded as the
        // config's display name, so the part that the 64-character skill name cannot hold is
        // still what the scouts list shows.
        await mountWithReports([])
        const typed = 'Robot: Replay Vision intent and friction report, every weekday morning'
        const config = makeConfig({ output_destinations: {} })
        mockScoutsCreate.mockResolvedValueOnce({ created: true, config } as any)
        jest.mocked(signalsScoutConfigUpdate).mockResolvedValue({ ...config, display_name: typed })

        logic.actions.createScout({
            name: typed,
            body: 'Watch this scanner.',
            cron: '0 9 * * *',
            outputDestinations: {},
            webhookUrl: '',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect((mockScoutsCreate.mock.calls[0][2] as any).name.length).toBeLessThanOrEqual(64)
        expect(signalsScoutConfigUpdate).toHaveBeenCalledWith(expect.any(String), config.id, {
            display_name: typed,
        })
    })

    it('leaves a scout whose skill name carries its name reading back off that name', async () => {
        // The name read off the skill name has the scanner in front of it, which is what tells two
        // scanners' digests apart in the fleet list. A display name that fits needs no override.
        await mountWithReports([])
        mockScoutsCreate.mockResolvedValueOnce({
            created: true,
            config: makeConfig({ output_destinations: {} }),
        } as any)

        logic.actions.createScout({
            name: 'Daily digest',
            body: 'Watch this scanner.',
            cron: '0 9 * * *',
            outputDestinations: {},
            webhookUrl: '',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(signalsScoutConfigUpdate).not.toHaveBeenCalledWith(
            expect.any(String),
            expect.any(String),
            expect.objectContaining({ display_name: expect.anything() })
        )
    })

    it('creates the scout even when its display name cannot be recorded', async () => {
        // The scout is already created by then, so a failed rename must not read as a failed create.
        await mountWithReports([])
        mockScoutsCreate.mockResolvedValueOnce({
            created: true,
            config: makeConfig({ output_destinations: {} }),
        } as any)
        jest.mocked(signalsScoutConfigUpdate).mockRejectedValue(new Error('boom'))

        logic.actions.createScout({
            name: 'Robot: Replay Vision intent and friction report, every weekday morning',
            body: 'Watch this scanner.',
            cron: '0 9 * * *',
            outputDestinations: {},
            webhookUrl: '',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockScoutsCreate).toHaveBeenCalledTimes(1)
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
