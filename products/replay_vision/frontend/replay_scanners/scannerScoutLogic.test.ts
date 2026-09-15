import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    hogFunctionsCreate,
    hogFunctionsPartialUpdate,
    hogFunctionsRetrieve,
} from 'products/cdp/frontend/generated/api'
import { signalsScoutConfigDestroy, signalsScoutConfigUpdate } from 'products/signals/frontend/generated/api'
import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import { scoutFleetLogic } from 'products/signals/frontend/inbox/logics/scoutFleetLogic'
import { scoutDisplayName } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'
import { llmSkillsNamePartialUpdate, llmSkillsNameRetrieve } from 'products/skills/frontend/generated/api'

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
const mockSkillRetrieve = llmSkillsNameRetrieve as jest.MockedFunction<typeof llmSkillsNameRetrieve>
const mockHogFunctionsCreate = hogFunctionsCreate as jest.MockedFunction<typeof hogFunctionsCreate>

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
        logic.actions.loadSkillPromptSuccess({ skillName: SKILL_NAME, body: 'Watch this scanner.', latestVersion: 3 })
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

    it('publishes edited instructions against the version the form was loaded at', async () => {
        await mountWithReports([])
        const config = makeConfig({ output_destinations: {} })
        scoutFleetLogic.findMounted()!.actions.loadScoutConfigsSuccess([config])
        logic.actions.openScoutSettings(SKILL_NAME)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadSkillPromptSuccess({ skillName: SKILL_NAME, body: 'Watch this scanner.', latestVersion: 3 })
        jest.mocked(llmSkillsNamePartialUpdate).mockResolvedValue({ body: 'Watch checkout.', version: 4 } as any)

        logic.actions.saveScoutSettings({
            name: scoutDisplayName(config),
            body: 'Watch checkout.',
            cron: config.run_cron_schedule!,
            outputDestinations: {},
            webhookUrl: '',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(llmSkillsNamePartialUpdate).toHaveBeenCalledWith(expect.any(String), SKILL_NAME, {
            body: 'Watch checkout.',
            base_version: 3,
        })
        expect(logic.values.skillPrompt).toEqual({ skillName: SKILL_NAME, body: 'Watch checkout.', latestVersion: 4 })
    })

    it('keeps the rename and the delivery when the instructions fail to publish', async () => {
        // The instructions PATCH is the only call here a concurrent edit can reject. Running it
        // before the others hands the rejection every other edit made in the same modal.
        await mountWithReports([])
        const config = makeConfig({ output_destinations: {} })
        scoutFleetLogic.findMounted()!.actions.loadScoutConfigsSuccess([config])
        logic.actions.openScoutSettings(SKILL_NAME)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadSkillPromptSuccess({ skillName: SKILL_NAME, body: 'Watch this scanner.', latestVersion: 3 })
        jest.mocked(signalsScoutConfigUpdate).mockResolvedValue({ ...config, display_name: 'Checkout / daily digest' })
        mockHogFunctionsCreate.mockResolvedValue({ id: 'hog-new' } as any)
        jest.mocked(llmSkillsNamePartialUpdate).mockRejectedValue({ status: 409 })

        logic.actions.saveScoutSettings({
            name: 'Checkout / daily digest',
            body: 'Watch checkout.',
            cron: config.run_cron_schedule!,
            outputDestinations: {},
            webhookUrl: 'https://example.com/hooks/scout',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(signalsScoutConfigUpdate).toHaveBeenCalledWith(expect.any(String), config.id, {
            display_name: 'Checkout / daily digest',
        })
        expect(mockHogFunctionsCreate).toHaveBeenCalled()
        expect(logic.values.settingsSkillName).toBe(SKILL_NAME)
    })

    it('refuses the save when the loaded instructions belong to another scout', async () => {
        // Nothing here can tell an edited body from an unchanged one without this scout's own
        // prompt. Saving the rest anyway drops the instruction edit and still reports success.
        await mountWithReports([])
        const config = makeConfig({ output_destinations: {} })
        scoutFleetLogic.findMounted()!.actions.loadScoutConfigsSuccess([config])
        logic.actions.openScoutSettings(SKILL_NAME)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadSkillPromptSuccess({
            skillName: 'signals-scout-weekly-digest',
            body: 'Watch another scanner.',
            latestVersion: 7,
        })

        logic.actions.saveScoutSettings({
            name: 'Checkout / daily digest',
            body: 'Watch checkout.',
            cron: config.run_cron_schedule!,
            outputDestinations: {},
            webhookUrl: '',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(signalsScoutConfigUpdate).not.toHaveBeenCalled()
        expect(llmSkillsNamePartialUpdate).not.toHaveBeenCalled()
        expect(logic.values.settingsSkillName).toBe(SKILL_NAME)
    })

    it('drops a slow read the user has already moved on from', async () => {
        // Two opens in a row leave two reads in flight. Without a breakpoint the slower one lands
        // last and puts the scout the user left behind under the form they are now looking at.
        await mountWithReports([])
        scoutFleetLogic.findMounted()!.actions.loadScoutConfigsSuccess([makeConfig()])
        let resolveFirst: (skill: unknown) => void = () => {}
        mockSkillRetrieve
            .mockReturnValueOnce(new Promise((resolve) => (resolveFirst = resolve)) as any)
            .mockResolvedValueOnce({
                body: 'Watch the other scanner.',
                body_total_length: 24,
                body_next_offset: null,
                version: 9,
                latest_version: 9,
            } as any)

        logic.actions.openScoutSettings(SKILL_NAME)
        logic.actions.openScoutSettings('signals-scout-weekly-digest')
        resolveFirst({
            body: 'Watch this scanner.',
            body_total_length: 19,
            body_next_offset: null,
            version: 3,
            latest_version: 3,
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.skillPrompt?.skillName).toBe('signals-scout-weekly-digest')
    })

    it('waits for a fresh read instead of reseeding the instructions a previous open left behind', async () => {
        // The form seeds from whatever the loader holds for this scout. Reopening after a conflict
        // with the stale body still in place seeds the losing text and the version it was read at,
        // so the next save publishes over the edit that caused the conflict.
        await mountWithReports([])
        scoutFleetLogic.findMounted()!.actions.loadScoutConfigsSuccess([makeConfig()])
        logic.actions.openScoutSettings(SKILL_NAME)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadSkillPromptSuccess({ skillName: SKILL_NAME, body: 'Watch this scanner.', latestVersion: 3 })

        logic.actions.openScoutSettings(SKILL_NAME)

        expect(logic.values.skillPrompt).toBeNull()
        expect(logic.values.scoutDelivery).toBeNull()
    })

    it.each<[string, string, string, number]>([
        ['another scout', 'signals-scout-trend-watch', 'Watch trends.', 9],
        ['the same scout', SKILL_NAME, 'Watch this scanner.', 3],
    ])(
        'publishes against the scout it started on and leaves %s alone when it is opened mid-save',
        async (_case, reopenedSkillName, reopenedBody, reopenedVersion) => {
            // Every request in the save can outlive its own modal, and nothing stops the user
            // opening a scout meanwhile. Reading the prompt after those requests anchors the publish
            // to the newly opened form's version and files this scout's body under it. Closing on
            // the way out throws away the draft that form holds. The scout name does not separate
            // the two forms, because the user can reopen the scout the save started on.
            await mountWithReports([])
            const config = makeConfig({ output_destinations: { webhook: null } })
            const other = makeConfig({
                id: 'config-2',
                skill_name: 'signals-scout-trend-watch',
                output_destinations: { webhook: null },
            })
            scoutFleetLogic.findMounted()!.actions.loadScoutConfigsSuccess([config, other])
            logic.actions.openScoutSettings(SKILL_NAME)
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.loadSkillPromptSuccess({
                skillName: SKILL_NAME,
                body: 'Watch this scanner.',
                latestVersion: 3,
            })

            let releaseRename: () => void = () => {}
            jest.mocked(signalsScoutConfigUpdate).mockReturnValue(
                new Promise((resolve) => (releaseRename = () => resolve({ ...config, display_name: 'Renamed' })))
            )
            jest.mocked(llmSkillsNamePartialUpdate).mockResolvedValue({ body: 'Watch checkout.', version: 4 } as any)
            mockSkillRetrieve.mockResolvedValue({
                body: reopenedBody,
                body_total_length: reopenedBody.length,
                body_next_offset: null,
                version: reopenedVersion,
                latest_version: reopenedVersion,
            } as any)

            logic.actions.saveScoutSettings({
                name: 'Renamed',
                body: 'Watch checkout.',
                cron: config.run_cron_schedule!,
                outputDestinations: { webhook: null },
                webhookUrl: '',
            })
            // The rename is still in flight when the user gives up on it and opens a scout again.
            logic.actions.closeScoutSettings()
            logic.actions.openScoutSettings(reopenedSkillName)
            logic.actions.loadSkillPromptSuccess({
                skillName: reopenedSkillName,
                body: reopenedBody,
                latestVersion: reopenedVersion,
            })
            releaseRename()
            await expectLogic(logic).toFinishAllListeners()

            expect(llmSkillsNamePartialUpdate).toHaveBeenCalledWith(expect.any(String), SKILL_NAME, {
                body: 'Watch checkout.',
                base_version: 3,
            })
            expect(logic.values.skillPrompt).toEqual({
                skillName: reopenedSkillName,
                body: reopenedBody,
                latestVersion: reopenedVersion,
            })
            expect(logic.values.settingsSkillName).toBe(reopenedSkillName)
        }
    )

    it('publishes the whole body when the instructions arrive over more than one page', async () => {
        await mountWithReports([])
        const config = makeConfig({ output_destinations: {} })
        scoutFleetLogic.findMounted()!.actions.loadScoutConfigsSuccess([config])
        const head = 'x'.repeat(8000)
        const tail = '\n\nFile the digest as one report.'
        mockSkillRetrieve
            .mockResolvedValueOnce({
                body: head,
                body_total_length: head.length + tail.length,
                body_next_offset: head.length,
                version: 3,
                latest_version: 3,
            } as any)
            .mockResolvedValueOnce({
                body: head + tail,
                body_total_length: head.length + tail.length,
                body_next_offset: null,
                version: 3,
                latest_version: 3,
            } as any)
        logic.actions.openScoutSettings(SKILL_NAME)
        await expectLogic(logic).toFinishAllListeners()
        const edited = `${head}${tail} Watch checkout.`
        jest.mocked(llmSkillsNamePartialUpdate).mockResolvedValue({ body: edited, version: 4 } as any)

        expect(mockSkillRetrieve).toHaveBeenLastCalledWith(expect.any(String), SKILL_NAME, {
            body_offset: 0,
            body_length: head.length + tail.length,
            version: 3,
        })
        expect(logic.values.skillPrompt).toEqual({ skillName: SKILL_NAME, body: head + tail, latestVersion: 3 })

        logic.actions.saveScoutSettings({
            name: scoutDisplayName(config),
            body: edited,
            cron: config.run_cron_schedule!,
            outputDestinations: {},
            webhookUrl: '',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(llmSkillsNamePartialUpdate).toHaveBeenCalledWith(expect.any(String), SKILL_NAME, {
            body: edited,
            base_version: 3,
        })
    })

    it('loads nothing when the instructions come back short', async () => {
        await mountWithReports([])
        scoutFleetLogic.findMounted()!.actions.loadScoutConfigsSuccess([makeConfig({ output_destinations: {} })])
        mockSkillRetrieve.mockResolvedValue({
            body: 'Watch this scanner.',
            body_total_length: 900,
            body_next_offset: null,
            version: 3,
            latest_version: 3,
        } as any)

        logic.actions.openScoutSettings(SKILL_NAME)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.skillPrompt).toBeNull()
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
