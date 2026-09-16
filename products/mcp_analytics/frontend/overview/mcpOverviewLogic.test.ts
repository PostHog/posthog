import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { MCPFailureGroup, MCPOverviewSummary, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { mcpOverviewLogic } from './mcpOverviewLogic'

jest.mock('lib/api')
jest.mock('lib/posthog-typed', () => ({ __esModule: true, default: { captureRaw: jest.fn() } }))
jest.mock('../generated/api', () => ({
    mcpAnalyticsSessionsIntentDigest: jest.fn().mockResolvedValue({ digest: null, intent_count: 0, themes: [] }),
}))

const mockApi = api as jest.Mocked<typeof api>

const SUMMARY: MCPOverviewSummary = {
    people: 48937,
    new_people: 15518,
    returning_people: 33419,
    new_people_first_call_failed_pct: 10.3,
    calls: 4140000,
    sessions: 318000,
    success_pct: 96,
    intent_pct: 88,
    clients: 28,
    automation_calls: 5260000,
    automation_sessions: 160000,
}

const HARNESS_ROWS = [
    { harness: 'Claude Code', total_calls: 1440000, errors: 82080, error_rate_pct: 5.7, sessions: 120000 },
    { harness: 'OpenAI Codex', total_calls: 1010000, errors: 20200, error_rate_pct: 2, sessions: 90000 },
    { harness: 'Other', total_calls: 637000, errors: 95550, error_rate_pct: 15, sessions: 50000 },
]

const UNKNOWN_TOOL_GROUP: MCPFailureGroup = {
    tool: 'exec',
    error_type: 'validation',
    message: 'Tool exec rejected the call: unknown_tool',
    sessions: 25300,
    calls: 75000,
    people: 9100,
    next_retried_succeeded_pct: 12,
    next_retried_failed_pct: 14,
    next_switched_pct: 63,
    next_ended_pct: 11,
    sample_intent: 'Looking for a tool that lists every dashboard in the project.',
}

function mockResultsByKind(resultsByKind: Partial<Record<NodeKind, unknown[]>>): void {
    mockApi.query.mockImplementation(
        async (node: any) => ({ results: resultsByKind[node.kind as NodeKind] ?? [] }) as any
    )
}

describe('mcpOverviewLogic', () => {
    let logic: ReturnType<typeof mcpOverviewLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        router.actions.push(urls.mcpAnalyticsOverview())
    })

    afterEach(() => {
        logic?.unmount()
    })

    async function mountAndLoad(): Promise<void> {
        logic = mcpOverviewLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('builds the headline from the summary and the top two resolved clients', async () => {
        mockResultsByKind({
            [NodeKind.MCPOverviewSummaryQuery]: [SUMMARY],
            [NodeKind.MCPHarnessBreakdownQuery]: HARNESS_ROWS,
        })
        await mountAndLoad()

        expect(logic.values.headline).toBe(
            '48.9K people used your server from 28 clients, mostly Claude Code and OpenAI Codex. ' +
                '96% of what they tried worked. ' +
                '15.5K of them were new, and 1 in 10 of those hit an error on their first call.'
        )
        // Unresolved clients rank last, so the bar list reads as real clients first.
        expect(logic.values.clientRows.map((row) => row.harness)).toEqual(['Claude Code', 'OpenAI Codex', 'Other'])
    })

    it('reports no activity rather than a sentence full of zeroes', async () => {
        mockResultsByKind({})
        await mountAndLoad()

        expect(logic.values.headline).toBe('No one called your MCP server in this range.')
    })

    it('counts only unknown-tool failure groups toward the missing-tools section', async () => {
        mockResultsByKind({
            [NodeKind.MCPFailureGroupsQuery]: [
                UNKNOWN_TOOL_GROUP,
                { ...UNKNOWN_TOOL_GROUP, message: 'execute-sql returned an error', sessions: 20800 },
            ],
        })
        await mountAndLoad()

        expect(logic.values.unknownToolSessions).toBe(25300)
    })

    it('marks unresolved clients and missing intent as things to fix', async () => {
        mockResultsByKind({
            [NodeKind.MCPOverviewSummaryQuery]: [{ ...SUMMARY, intent_pct: 46 }],
            [NodeKind.MCPHarnessBreakdownQuery]: HARNESS_ROWS,
        })
        await mountAndLoad()

        const badgeByKey = Object.fromEntries(logic.values.coverageItems.map((item) => [item.key, item.badge]))
        expect(badgeByKey.intent).toBe('Fix')
        expect(badgeByKey.clients).toBe('Fix')
        expect(badgeByKey.model).toBe('Info')
    })

    it('scopes every query to the selected caller kind and keeps it in the URL', async () => {
        mockResultsByKind({})
        await mountAndLoad()

        await expectLogic(logic, () => logic.actions.setCallerKind('automations')).toFinishAllListeners()

        expect(router.values.searchParams.caller_kind).toBe('automations')
        const summaryCallerKinds = mockApi.query.mock.calls
            .map(([node]) => node as { kind: NodeKind; callerKind?: string })
            .filter((node) => node.kind === NodeKind.MCPOverviewSummaryQuery)
            .map((node) => node.callerKind)
        expect(summaryCallerKinds).toEqual(['people', 'automations'])
    })

    it('drops caller_kind from the URL once it returns to the default', async () => {
        mockResultsByKind({})
        await mountAndLoad()

        await expectLogic(logic, () => logic.actions.setCallerKind('all')).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.setCallerKind('people')).toFinishAllListeners()

        expect(router.values.searchParams.caller_kind).toBeUndefined()
    })
})
