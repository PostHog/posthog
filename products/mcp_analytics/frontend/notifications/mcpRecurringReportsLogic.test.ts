import { expectLogic } from 'kea-test-utils'

import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { initKeaTests } from '~/test/init'

import { toggleSubscriptionEnabled } from 'products/subscriptions/frontend/components/Subscriptions/toggleSubscriptionEnabled'
import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'
import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { isMCPRecurringReport, mcpRecurringReportsLogic } from './mcpRecurringReportsLogic'

jest.mock('lib/utils/deleteWithUndo', () => ({ deleteWithUndo: jest.fn() }))
jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsList: jest.fn(),
}))
jest.mock('products/subscriptions/frontend/components/Subscriptions/toggleSubscriptionEnabled', () => ({
    toggleSubscriptionEnabled: jest.fn(),
}))

const mockedDeleteWithUndo = jest.mocked(deleteWithUndo)
const mockedList = jest.mocked(subscriptionsList)
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
})
