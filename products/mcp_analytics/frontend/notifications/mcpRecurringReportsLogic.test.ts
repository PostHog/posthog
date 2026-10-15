import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import posthog from 'lib/posthog-typed'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { organizationLogic } from 'scenes/organizationLogic'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType, OrganizationType, UserType } from '~/types'

import { toggleSubscriptionEnabled } from 'products/subscriptions/frontend/components/Subscriptions/toggleSubscriptionEnabled'
import { subscriptionsCreate, subscriptionsList } from 'products/subscriptions/frontend/generated/api'
import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { isMCPRecurringReport, mcpRecurringReportsLogic } from './mcpRecurringReportsLogic'
import { MCP_RECURRING_REPORTS, TOOL_HEALTH_REPORT } from './recurringReportDefinitions'

jest.mock('lib/lemon-ui/LemonToast', () => ({ lemonToast: { success: jest.fn(), error: jest.fn() } }))
jest.mock('lib/utils/deleteWithUndo', () => ({ deleteWithUndo: jest.fn() }))
jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { capture: jest.fn(), captureRaw: jest.fn() } }))
jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsList: jest.fn(),
    subscriptionsCreate: jest.fn(),
}))
jest.mock('products/subscriptions/frontend/components/Subscriptions/toggleSubscriptionEnabled', () => ({
    toggleSubscriptionEnabled: jest.fn(),
}))

const mockedDeleteWithUndo = jest.mocked(deleteWithUndo)
const mockedList = jest.mocked(subscriptionsList)
const mockedCreate = jest.mocked(subscriptionsCreate)
const mockedCaptureRaw = jest.mocked(posthog.captureRaw)
const mockedToggle = jest.mocked(toggleSubscriptionEnabled)

const MCP_PROMPT = 'Summarize $mcp_intent on $mcp_tool_call events this week.'

function makeReport(id: number, overrides: Partial<SubscriptionApi> = {}): SubscriptionApi {
    return {
        id,
        title: `Report ${id}`,
        prompt: MCP_PROMPT,
        enabled: true,
        deleted: false,
        summary: 'sent every week on the first Monday',
        next_delivery_date: '2026-08-10T12:00:00Z',
        ...overrides,
    } as SubscriptionApi
}

function listReturns(results: SubscriptionApi[], next: string | null = null): void {
    mockedList.mockResolvedValue({ next, previous: null, results } as any)
}

describe('mcpRecurringReportsLogic', () => {
    let logic: ReturnType<typeof mcpRecurringReportsLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockedDeleteWithUndo.mockReset().mockResolvedValue()
        mockedToggle.mockReset().mockResolvedValue(true)
        mockedList.mockReset()
        mockedCreate.mockReset()
        mockedCaptureRaw.mockClear()
        listReturns([])

        logic = mcpRecurringReportsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // The Subscription model has no provenance field, so an ai_prompt report is identified by whether it
    // actually queries MCP data. These are the cases that decide whether a row reaches the tab at all.
    it.each([
        ['names an $mcp_ property', MCP_PROMPT, true],
        ['names $mcp_ mid-sentence', 'Report on $mcp_tool_call errors.', true],
        ['only says the word MCP', 'Summarize how our MCP server did this week.', false],
        ['is about something else', 'Summarize $pageview trends.', false],
        ['has no prompt at all', null, false],
    ])('%s -> %s', (_name, prompt, expected) => {
        expect(isMCPRecurringReport({ prompt })).toBe(expected)
    })

    it('groups saved reports by template title and keeps renamed or untitled ones under other', async () => {
        listReturns([
            makeReport(1, { title: MCP_RECURRING_REPORTS[0].title }),
            makeReport(2, { title: 'Renamed report' }),
            makeReport(3, { title: '' }),
        ])

        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()

        expect(logic.values.reportsByTemplateTitle[MCP_RECURRING_REPORTS[0].title].map((r) => r.id)).toEqual([1])
        expect(logic.values.reportsByTemplateTitle[MCP_RECURRING_REPORTS[1].title]).toEqual([])
        expect(logic.values.otherReports.map((r) => r.id)).toEqual([2, 3])
    })

    const ME = 'user-me'
    const createdBy = (id: number, target_type: string, uuid: string | null): SubscriptionApi =>
        makeReport(id, { target_type, created_by: uuid ? { uuid } : null } as Partial<SubscriptionApi>)

    async function loadDefaultInputs(slackConnected: boolean): Promise<void> {
        userLogic.actions.loadUserSuccess({ uuid: ME } as UserType)
        await expectLogic(integrationsLogic).toFinishAllListeners()
        integrationsLogic.actions.loadIntegrationsSuccess(
            slackConnected ? [{ id: 1, kind: 'slack' } as IntegrationType] : []
        )
    }

    // Reports arrive newest first, as the API orders them.
    it.each([
        ['my most recent report wins', [createdBy(2, 'teams', ME), createdBy(1, 'email', ME)], true, 'teams'],
        ['a teammate report is not my choice', [createdBy(1, 'teams', 'someone-else')], false, 'email'],
        ['a report with a deleted creator is not my choice', [createdBy(1, 'teams', null)], false, 'email'],
        ['no report of mine, Slack connected', [createdBy(1, 'email', 'someone-else')], true, 'slack'],
        ['no report and no Slack', [], false, 'email'],
    ])('defaults the destination when %s', async (_name, reports, slackConnected, expected) => {
        await loadDefaultInputs(slackConnected)
        listReturns(reports)

        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()

        expect(logic.values.defaultTargetType).toBe(expected)
    })

    it('has no default destination until the reports load', async () => {
        await loadDefaultInputs(true)

        expect(logic.values.defaultTargetType).toBeNull()
    })

    it('lists only the MCP reports among the project AI reports', async () => {
        const mcpReport = makeReport(1)
        listReturns([mcpReport, makeReport(2, { prompt: 'Weekly $pageview summary.' })])

        await expectLogic(logic, () => logic.actions.loadReports())
            .toFinishAllListeners()
            .toMatchValues({ reports: [mcpReport], reportsLoaded: true, reportsFailed: false })

        // The prompt match happens server-side, so only MCP rows cross the wire; the client-side
        // filter is the precise re-check (search also spans title and insight/dashboard names).
        expect(mockedList).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ resource_type: 'ai_prompt', search: '$mcp_' })
        )
    })

    it.each([
        ['flags truncation when the server has more', 'http://localhost/api/.../?offset=200', true],
        ['does not flag a complete page', null, false],
    ])('%s', async (_name, next, expected) => {
        // A report the tab silently omits is the exact bug this section exists to fix, so a capped
        // list has to say so rather than just ending.
        listReturns([makeReport(1)], next as string | null)

        await expectLogic(logic, () => logic.actions.loadReports())
            .toFinishAllListeners()
            .toMatchValues({ reportsTruncated: expected })
    })

    it('drops soft-deleted reports', async () => {
        listReturns([makeReport(1, { deleted: true }), makeReport(2)])

        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()

        expect(logic.values.reports.map((report) => report.id)).toEqual([2])
    })

    it('flags a failed load so the banner can offer a retry', async () => {
        mockedList.mockRejectedValue(new Error('nope'))

        await expectLogic(logic, () => logic.actions.loadReports())
            .toFinishAllListeners()
            .toMatchValues({ reportsFailed: true, reportsLoaded: true })
    })

    it('reverts the toggle when the update is rejected', async () => {
        listReturns([makeReport(1, { enabled: true })])
        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()
        mockedToggle.mockResolvedValue(false)

        await expectLogic(logic, () => logic.actions.toggleReportEnabled(1, false)).toFinishAllListeners()

        expect(logic.values.reports[0].enabled).toBe(true)
        expect(logic.values.pendingToggleIds).toEqual({})
    })

    it('keeps the toggle when the update succeeds', async () => {
        listReturns([makeReport(1, { enabled: true })])
        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.toggleReportEnabled(1, false)).toFinishAllListeners()

        expect(logic.values.reports[0].enabled).toBe(false)
        expect(mockedToggle).toHaveBeenCalledWith(1, false)
    })

    it('restores a deleted report when the delete is undone', async () => {
        listReturns([makeReport(1), makeReport(2)])
        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()
        mockedDeleteWithUndo.mockImplementation(async ({ callback }: any) => callback(true, {}))

        await expectLogic(logic, () => logic.actions.deleteReport(logic.values.reports[0])).toFinishAllListeners()

        expect(logic.values.reports.map((report) => report.id)).toEqual([1, 2])
    })

    it('drops a deleted report from the list', async () => {
        listReturns([makeReport(1), makeReport(2)])
        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()
        mockedDeleteWithUndo.mockImplementation(async ({ callback }: any) => callback(false, {}))

        await expectLogic(logic, () => logic.actions.deleteReport(logic.values.reports[0])).toFinishAllListeners()

        expect(logic.values.reports.map((report) => report.id)).toEqual([2])
    })

    it('puts the row back when the delete fails', async () => {
        // deleteWithUndo swallows its own API errors and resolves without calling back, so the row
        // would otherwise stay optimistically gone while the report is alive and still delivering.
        listReturns([makeReport(1), makeReport(2)])
        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()
        mockedDeleteWithUndo.mockResolvedValue()

        await expectLogic(logic, () => logic.actions.deleteReport(logic.values.reports[0])).toFinishAllListeners()

        expect(logic.values.reports.map((report) => report.id).sort()).toEqual([1, 2])
    })

    it('undoing one delete does not resurrect a different deleted report', async () => {
        // Restoring from a whole-list snapshot would replay the state before the second delete.
        listReturns([makeReport(1), makeReport(2)])
        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()

        const [first, second] = logic.values.reports
        let undoFirst: (() => void) | undefined
        mockedDeleteWithUndo.mockImplementation(async ({ object, callback }: any) => {
            if (object.id === first.id) {
                undoFirst = () => callback(true, object)
            } else {
                callback(false, object)
            }
        })

        await expectLogic(logic, () => logic.actions.deleteReport(first)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.deleteReport(second)).toFinishAllListeners()
        undoFirst?.()

        expect(logic.values.reports.map((report) => report.id)).toEqual([first.id])
    })

    describe('creating the weekly report', () => {
        const SAVED = makeReport(9, {
            title: TOOL_HEALTH_REPORT.title,
            target_type: 'email',
        } as Partial<SubscriptionApi>)
        const FALLBACK_MESSAGE = "Couldn't create the report. Try again, or set it up from the Notifications tab."

        async function becomeReadyToCreate(): Promise<void> {
            // Let the mounted preflight request land first, so it cannot overwrite the answer set here.
            await expectLogic(preflightLogic).toFinishAllListeners()
            preflightLogic.actions.loadPreflightSuccess({ cloud: true, is_debug: false } as any)
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT], {
                [FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT]: true,
            })
            userLogic.actions.loadUserSuccess({ uuid: 'user-me', email: 'me@example.com' } as UserType)
            await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()
        }

        it('is ready once everything it depends on has loaded', async () => {
            await becomeReadyToCreate()

            expect(logic.values.weeklyReportOffer).toEqual({ state: 'ready', email: 'me@example.com' })
        })

        it('creates one report when clicked twice while the first request is in flight', async () => {
            await becomeReadyToCreate()
            let finishCreate: (report: SubscriptionApi) => void = () => {}
            mockedCreate.mockReturnValue(new Promise((resolve) => (finishCreate = resolve)))

            logic.actions.createWeeklyReport()
            logic.actions.createWeeklyReport()
            expect(logic.values.weeklyReportOffer).toEqual({ state: 'creating', email: 'me@example.com' })
            finishCreate(SAVED)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockedCreate).toHaveBeenCalledTimes(1)
            expect(logic.values.weeklyReportOffer).toEqual({ state: 'created', report: SAVED })
        })

        it('sends the tool health report to the user, weekly, with no immediate send', async () => {
            await becomeReadyToCreate()
            mockedCreate.mockResolvedValue(SAVED)

            await expectLogic(logic, () => logic.actions.createWeeklyReport()).toFinishAllListeners()

            expect(mockedCreate).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({
                    title: TOOL_HEALTH_REPORT.title,
                    prompt: TOOL_HEALTH_REPORT.prompt,
                    target_type: 'email',
                    target_value: 'me@example.com',
                    frequency: 'weekly',
                    send_test_now: false,
                })
            )
        })

        it('files the new report under its template and reports the creation', async () => {
            await becomeReadyToCreate()
            mockedCreate.mockResolvedValue(SAVED)

            await expectLogic(logic, () => logic.actions.createWeeklyReport()).toFinishAllListeners()

            expect(logic.values.reportsByTemplateTitle[TOOL_HEALTH_REPORT.title]).toEqual([SAVED])
            expect(mockedCaptureRaw).toHaveBeenCalledWith('subscription created', {
                creation_source: 'mcp_analytics_one_click',
                resource_type: 'ai',
                subscription_id: 9,
                target_type: 'email',
                mcp_report_template: 'tool-health',
            })
        })

        it.each([
            [
                'the server explains',
                new ApiError('Bad Request', 400, undefined, { detail: 'Your plan is limited to 5 subscriptions.' }),
                'Your plan is limited to 5 subscriptions.',
                false,
            ],
            ['the server fails', new ApiError('Server Error', 500), FALLBACK_MESSAGE, true],
            ['the network fails', new TypeError('Failed to fetch'), FALLBACK_MESSAGE, true],
        ])('fails with a message and allows a retry when %s', async (_name, error, message, reloadsList) => {
            await becomeReadyToCreate()
            const listCallsBefore = mockedList.mock.calls.length
            mockedCreate.mockRejectedValueOnce(error).mockResolvedValueOnce(SAVED)

            await expectLogic(logic, () => logic.actions.createWeeklyReport()).toFinishAllListeners()
            expect(logic.values.weeklyReportOffer).toEqual({ state: 'failed', email: 'me@example.com', message })
            expect(logic.values.reports).toEqual([])
            expect(mockedList).toHaveBeenCalledTimes(listCallsBefore + (reloadsList ? 1 : 0))
            expect(mockedCaptureRaw).toHaveBeenCalledWith(
                'mcp analytics weekly report failed',
                expect.objectContaining({ mcp_report_template: 'tool-health', error_message: message })
            )

            await expectLogic(logic, () => logic.actions.createWeeklyReport()).toFinishAllListeners()
            expect(logic.values.weeklyReportOffer).toEqual({ state: 'created', report: SAVED })
        })

        it('resolves to has-report, not a duplicate retry, when the request landed despite the failure', async () => {
            await becomeReadyToCreate()
            mockedCreate.mockRejectedValueOnce(new TypeError('Failed to fetch'))
            listReturns([SAVED])

            await expectLogic(logic, () => logic.actions.createWeeklyReport()).toFinishAllListeners()

            expect(logic.values.weeklyReportOffer).toEqual({ state: 'hidden', reason: 'has-report' })
        })

        it('creates the report once the organization approves AI processing', async () => {
            useMocks({
                patch: {
                    '/api/organizations/:id': async ({ request }) => [
                        200,
                        { ...MOCK_DEFAULT_ORGANIZATION, ...((await request.json()) as object) },
                    ],
                },
            })
            await becomeReadyToCreate()
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...organizationLogic.values.currentOrganization,
                is_ai_data_processing_approved: false,
            } as OrganizationType)
            expect(logic.values.weeklyReportOffer).toEqual({ state: 'needs-ai-consent', email: 'me@example.com' })
            mockedCreate.mockResolvedValue(SAVED)
            const consent = aiConsentLogic.build()
            consent.mount()

            // The order the consent popover runs on approve: the approval resolves, then the report is created.
            await consent.asyncActions.acceptDataProcessing()
            await expectLogic(logic, () => logic.actions.createWeeklyReport()).toFinishAllListeners()
            consent.unmount()

            expect(mockedCreate).toHaveBeenCalledTimes(1)
            expect(logic.values.weeklyReportOffer).toEqual({ state: 'created', report: SAVED })
        })

        it.each([
            [
                'the project already has an MCP report',
                async () => {
                    listReturns([makeReport(1)])
                    await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()
                },
                'hidden',
            ],
            [
                'the organization has not approved AI processing',
                () =>
                    organizationLogic.actions.loadCurrentOrganizationSuccess({
                        ...organizationLogic.values.currentOrganization,
                        is_ai_data_processing_approved: false,
                    } as OrganizationType),
                'needs-ai-consent',
            ],
            [
                'the instance is self-hosted',
                () => preflightLogic.actions.loadPreflightSuccess({ cloud: false, is_debug: false } as any),
                'hidden',
            ],
            ['the feature flag is off', () => featureFlagLogic.actions.setFeatureFlags([], {}), 'hidden'],
        ])('does not create when %s', async (_name, block, expectedState) => {
            await becomeReadyToCreate()
            await block()

            await expectLogic(logic, () => logic.actions.createWeeklyReport()).toFinishAllListeners()

            expect(mockedCreate).not.toHaveBeenCalled()
            expect(logic.values.weeklyReportOffer.state).toBe(expectedState)
        })
    })
})
