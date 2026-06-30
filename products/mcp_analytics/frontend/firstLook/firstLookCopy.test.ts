import type { KPIData, ToolRow } from '../mcpDashboardOverviewLogic'
import { buildChips, buildEditorPrompt, buildHeadline, buildMaxPrompt } from './firstLookCopy'

const metric = (value: number): KPIData['sessions'] => ({
    value,
    previousValue: 0,
    deltaPct: null,
    sparkline: [],
    goodDirection: 'up',
})

const KPIS: KPIData = {
    sessions: metric(120),
    toolCalls: metric(1480),
    errorRatePct: metric(9),
    p95LatencyMs: metric(3525),
}

const tool = (over: Partial<ToolRow> = {}): ToolRow => ({
    tool: 'execute-sql',
    total_calls: 1480,
    errors: 144,
    error_rate_pct: 9.7,
    p95_duration_ms: 3525,
    ...over,
})

describe('firstLookCopy', () => {
    describe('buildHeadline', () => {
        it('names the company, dominant client, busiest tool, and flags a flaky one', () => {
            const headline = buildHeadline({
                company: 'Acme',
                project: 'prod',
                topTool: tool(),
                client: 'Claude Code',
                kpis: KPIS,
            })
            expect(headline).toContain("Acme's MCP server is live")
            expect(headline).toContain('Claude Code agents')
            expect(headline).toContain('execute-sql')
            expect(headline).toContain('errors 9.7% of the time')
        })

        it('omits the client phrase and the flaky clause when not warranted', () => {
            const headline = buildHeadline({
                company: null,
                project: 'prod',
                topTool: tool({ error_rate_pct: 1 }),
                client: null,
                kpis: KPIS,
            })
            expect(headline).toContain("prod's MCP server is live")
            expect(headline).toContain('Agents leaned on')
            expect(headline).not.toContain('agents leaned on') // no client prefix
            expect(headline).not.toContain('errors')
        })

        it('falls back to top-line counts when no per-tool rows resolved', () => {
            const headline = buildHeadline({ company: null, project: null, topTool: null, client: null, kpis: KPIS })
            expect(headline).toContain('Your MCP server is live')
            expect(headline).toContain('tool calls across')
            expect(headline).toContain('sessions so far')
        })
    })

    describe('buildMaxPrompt', () => {
        it('references the worst error tool and its rate', () => {
            const prompt = buildMaxPrompt({
                worstErrorTool: tool({ tool: 'cohort-create', error_rate_pct: 6.3 }),
                topTool: tool(),
            })
            expect(prompt).toContain('cohort-create')
            expect(prompt).toContain('6.3%')
            expect(prompt).toContain('$mcp_tool_call')
        })

        it('asks a trend question on the busiest tool when nothing errors', () => {
            const prompt = buildMaxPrompt({
                worstErrorTool: tool({ error_rate_pct: 0 }),
                topTool: tool({ tool: 'read-data-schema' }),
            })
            expect(prompt).toContain('read-data-schema')
            expect(prompt).toContain('trended')
        })
    })

    describe('buildEditorPrompt', () => {
        it('targets the detected client', () => {
            expect(buildEditorPrompt({ client: 'Cursor' }).label).toBe('Paste this into Cursor')
            expect(buildEditorPrompt({ client: 'OpenAI Codex' }).label).toBe('Paste this into Codex')
        })

        it('falls back to a generic target for unknown or missing clients', () => {
            expect(buildEditorPrompt({ client: null }).label).toBe('Paste this into your agent')
            expect(buildEditorPrompt({ client: 'Some New Agent' }).label).toBe('Paste this into your agent')
        })
    })

    describe('buildChips', () => {
        it('drops chips whose data is missing', () => {
            expect(
                buildChips({
                    topTool: null,
                    worstErrorTool: null,
                    kpis: { ...KPIS, p95LatencyMs: metric(0) },
                    client: null,
                })
            ).toEqual([])
        })

        it('drops the flakiest chip when it is the same tool as the busiest', () => {
            const chips = buildChips({
                topTool: tool({ tool: 'execute-sql' }),
                worstErrorTool: tool({ tool: 'execute-sql', error_rate_pct: 12 }),
                kpis: KPIS,
                client: null,
            })
            expect(chips.map((c) => c.key)).toEqual(['top-tool', 'p95'])
        })

        it('includes all four when data is present, in order', () => {
            const chips = buildChips({
                topTool: tool(),
                worstErrorTool: tool({ tool: 'cohort-create', error_rate_pct: 12 }),
                kpis: KPIS,
                client: 'Cursor',
            })
            expect(chips.map((c) => c.key)).toEqual(['top-tool', 'worst-error', 'p95', 'client'])
            expect(chips.find((c) => c.key === 'worst-error')?.tone).toBe('danger')
            expect(chips.find((c) => c.key === 'client')?.harness).toBe('Cursor')
        })
    })
})
