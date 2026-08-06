import { expectLogic } from 'kea-test-utils'

import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { initKeaTests } from '~/test/init'

import { toggleSubscriptionEnabled } from 'products/subscriptions/frontend/components/Subscriptions/toggleSubscriptionEnabled'
import { subscriptionsDeliveriesList, subscriptionsList } from 'products/subscriptions/frontend/generated/api'
import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { isMCPRecurringReport, mcpRecurringReportsLogic } from './mcpRecurringReportsLogic'

jest.mock('lib/utils/deleteWithUndo', () => ({ deleteWithUndo: jest.fn() }))
jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsList: jest.fn(),
    subscriptionsDeliveriesList: jest.fn(),
}))
jest.mock('products/subscriptions/frontend/components/Subscriptions/toggleSubscriptionEnabled', () => ({
    toggleSubscriptionEnabled: jest.fn(),
}))

const mockedDeleteWithUndo = jest.mocked(deleteWithUndo)
const mockedList = jest.mocked(subscriptionsList)
const mockedDeliveries = jest.mocked(subscriptionsDeliveriesList)
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

function listReturns(results: SubscriptionApi[]): void {
    mockedList.mockResolvedValue({ next: null, previous: null, results } as any)
}

describe('mcpRecurringReportsLogic', () => {
    let logic: ReturnType<typeof mcpRecurringReportsLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockedDeleteWithUndo.mockReset().mockResolvedValue()
        mockedToggle.mockReset().mockResolvedValue(true)
        mockedDeliveries.mockReset().mockResolvedValue({ next: null, previous: null, results: [] } as any)
        mockedList.mockReset()
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

    it('lists only the MCP reports among the project AI reports', async () => {
        const mcpReport = makeReport(1)
        listReturns([mcpReport, makeReport(2, { prompt: 'Weekly $pageview summary.' })])

        await expectLogic(logic, () => logic.actions.loadReports())
            .toFinishAllListeners()
            .toMatchValues({ reports: [mcpReport], reportsLoaded: true, reportsFailed: false })

        expect(mockedList).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ resource_type: 'ai_prompt' })
        )
    })

    it('drops soft-deleted reports', async () => {
        listReturns([makeReport(1, { deleted: true }), makeReport(2)])

        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()

        expect(logic.values.reports.map((report) => report.id)).toEqual([2])
    })

    it('surfaces a failed last run', async () => {
        listReturns([makeReport(1)])
        mockedDeliveries.mockResolvedValue({
            next: null,
            previous: null,
            results: [{ id: 'd1', subscription: 1, status: 'failed' }],
        } as any)

        await expectLogic(logic, () => logic.actions.loadReports())
            .toFinishAllListeners()
            .toMatchValues({ deliveryStatuses: { 1: 'failed' } })
    })

    it('still lists a report when its status lookup fails', async () => {
        // The status decorates a row we can already render, so losing it must not lose the row.
        listReturns([makeReport(1)])
        mockedDeliveries.mockRejectedValue(new Error('boom'))

        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()

        expect(logic.values.reports.map((report) => report.id)).toEqual([1])
        expect(logic.values.deliveryStatuses).toEqual({})
    })

    it('skips the delivery lookup entirely when there are no reports', async () => {
        await expectLogic(logic, () => logic.actions.loadReports()).toFinishAllListeners()

        expect(mockedDeliveries).not.toHaveBeenCalled()
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
})
