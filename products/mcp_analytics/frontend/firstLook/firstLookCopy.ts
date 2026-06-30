import { formatMs, formatNumber } from '../dashboard/formatters'
import type { KPIData, ToolRow } from '../mcpDashboardOverviewLogic'

// At/above this error rate we call the tool out as flaky in the headline.
const FLAKY_ERROR_RATE_PCT = 5

export interface FirstLookChip {
    key: string
    label: string
    value: string
    tone?: 'danger'
    /** When set, render this harness's logo in place of an icon. */
    harness?: string
}

const possessive = (company?: string | null, project?: string | null): string =>
    company ? `${company}'s` : project ? `${project}'s` : 'Your'

/** One-line, personalized "your server is live" headline derived from real metrics. */
export function buildHeadline({
    company,
    project,
    topTool,
    client,
    kpis,
}: {
    company?: string | null
    project?: string | null
    topTool: ToolRow | null
    client: string | null
    kpis: KPIData
}): string {
    const who = possessive(company, project)
    if (topTool) {
        const agents = client ? `${client} agents` : 'Agents'
        const flaky =
            topTool.error_rate_pct >= FLAKY_ERROR_RATE_PCT
                ? `, though it errors ${topTool.error_rate_pct}% of the time`
                : ''
        return `${who} MCP server is live — ${agents} leaned on ${topTool.tool} ${formatNumber(topTool.total_calls)} times, your busiest tool${flaky}.`
    }
    // No per-tool rows resolved yet — fall back to top-line counts.
    return `${who} MCP server is live — ${formatNumber(kpis.toolCalls.value)} tool calls across ${formatNumber(kpis.sessions.value)} sessions so far.`
}

/** A concrete question for PostHog AI, tied to their actual worst tool so the answer is useful. */
export function buildMaxPrompt({
    worstErrorTool,
    topTool,
}: {
    worstErrorTool: ToolRow | null
    topTool: ToolRow | null
}): string {
    if (worstErrorTool && worstErrorTool.error_rate_pct > 0) {
        return `My MCP server's ${worstErrorTool.tool} tool errors ${worstErrorTool.error_rate_pct}% of the time over ${formatNumber(worstErrorTool.total_calls)} $mcp_tool_call events. Show me the most common errors and what's causing them.`
    }
    if (topTool) {
        return `My busiest MCP tool is ${topTool.tool}. Show me how its usage and latency have trended over the last 7 days and whether anything looks anomalous.`
    }
    return `Summarize how agents are using my MCP server from $mcp_tool_call events — top tools, error rates, and what they're trying to do.`
}

// Friendly harness label → where to paste the prompt. Falls back to "your agent".
const HARNESS_PASTE_TARGET: Record<string, string> = {
    'Claude Code': 'Claude Code',
    'Claude Desktop': 'Claude Desktop',
    'Claude Code (VS Code)': 'Claude Code',
    Cursor: 'Cursor',
    'OpenAI Codex': 'Codex',
    'VS Code': 'VS Code',
    Windsurf: 'Windsurf',
}

/** A copy-paste prompt for the customer's own coding agent, framed for their dominant client. */
export function buildEditorPrompt({ client }: { client: string | null }): { label: string; prompt: string } {
    const where = (client && HARNESS_PASTE_TARGET[client]) || 'your agent'
    return {
        label: `Paste this into ${where}`,
        prompt: 'Using the PostHog MCP, pull my $mcp_tool_call events and tell me which tools error most and why.',
    }
}

/** Metric highlight chips; any chip whose data is missing is dropped. */
export function buildChips({
    topTool,
    worstErrorTool,
    kpis,
    client,
}: {
    topTool: ToolRow | null
    worstErrorTool: ToolRow | null
    kpis: KPIData
    client: string | null
}): FirstLookChip[] {
    const chips: FirstLookChip[] = []
    if (topTool) {
        chips.push({ key: 'top-tool', label: 'Busiest tool', value: topTool.tool })
    }
    // Skip the flakiest chip when it's the same tool as the busiest one — the busiest chip
    // and the headline's flaky clause already name it; a third mention reads as noise.
    if (worstErrorTool && worstErrorTool.error_rate_pct > 0 && worstErrorTool.tool !== topTool?.tool) {
        chips.push({
            key: 'worst-error',
            label: 'Flakiest tool',
            value: `${worstErrorTool.tool} · ${worstErrorTool.error_rate_pct}%`,
            tone: 'danger',
        })
    }
    if (kpis.p95LatencyMs.value > 0) {
        chips.push({ key: 'p95', label: 'p95 latency', value: formatMs(kpis.p95LatencyMs.value) })
    }
    if (client) {
        chips.push({ key: 'client', label: 'Top client', value: client, harness: client })
    }
    return chips
}
