import { urls } from 'scenes/urls'

import type {
    MCPHarnessBreakdownItem,
    MCPModelBreakdownItem,
    MCPOverviewSummary,
} from '~/queries/schema/schema-general'

import {
    type ChecklistItem,
    type ChecklistStatus,
    type EarlyStats,
    buildChecklist,
} from '../earlyData/earlyDataChecklist'
import { formatPct, isUnresolvedHarness } from './overviewCopy'

export type CoverageBadge = 'OK' | 'Fix' | 'Info'

export interface CoverageItem {
    key: string
    badge: CoverageBadge
    title: string
    detail: string
    link?: { to: string; label: string }
}

const DOCS_INTENT = 'https://posthog.com/docs/mcp-analytics/intent'
const DOCS_CLIENT_NAME = 'https://posthog.com/docs/mcp-analytics/installation'
const DOCS_MISSING_CAPABILITY = 'https://posthog.com/docs/mcp-analytics/missing-capability'

/** Below this, the intent themes summarize too little of the traffic to stand on. */
const INTENT_OK_PCT = 80
/** Above this share of unresolved clients, the "by client" split stops being a split. */
const UNRESOLVED_CLIENTS_FIX_PCT = 5

const BADGE_FOR_STATUS: Record<ChecklistStatus, CoverageBadge> = { ok: 'OK', warning: 'Fix', pending: 'Info' }

/**
 * The instrumentation checks the early-data view already makes, restated for this card. Their
 * inputs are counts, so the overview's own window can stand in for the early view's fixed one.
 */
function overviewAsEarlyStats(summary: MCPOverviewSummary | null): EarlyStats {
    return {
        totalCalls: summary?.calls ?? 0,
        // Only the checks below are read here, and none of them look at the tool count.
        distinctTools: 0,
        distinctSessions: summary?.sessions ?? 0,
        distinctClients: summary?.clients ?? 0,
        callsWithIntent: summary ? Math.round((summary.calls * summary.intent_pct) / 100) : 0,
        errorCalls: summary ? Math.round((summary.calls * (100 - summary.success_pct)) / 100) : 0,
        // Reported separately below, because the overview only fetches enough reports to show one.
        missingCapabilityReports: 0,
    }
}

function fromChecklistItem(item: ChecklistItem): CoverageItem {
    return {
        key: item.key,
        badge: BADGE_FOR_STATUS[item.status],
        title: item.title,
        detail: item.detail,
        link: item.appLink ?? (item.status === 'ok' ? undefined : { to: item.docsUrl, label: 'How to set it up' }),
    }
}

function intentItem(summary: MCPOverviewSummary | null): CoverageItem {
    const intentPct = summary?.intent_pct ?? 0
    const isOk = intentPct >= INTENT_OK_PCT
    return {
        key: 'intent',
        badge: isOk ? 'OK' : 'Fix',
        title: `Intent on ${formatPct(intentPct)} of calls`,
        detail: isOk
            ? 'Enough of the traffic to group what people are trying to do.'
            : 'The themes above only cover calls that carry intent. Pass the context parameter on every tool call.',
        link: isOk ? undefined : { to: DOCS_INTENT, label: 'How to set it up' },
    }
}

function clientItem(harnessRows: readonly MCPHarnessBreakdownItem[]): CoverageItem {
    const totalCalls = harnessRows.reduce((sum, row) => sum + row.total_calls, 0)
    const unresolvedCalls = harnessRows
        .filter((row) => isUnresolvedHarness(row.harness))
        .reduce((sum, row) => sum + row.total_calls, 0)
    const unresolvedPct = totalCalls > 0 ? (unresolvedCalls / totalCalls) * 100 : 0
    const isOk = unresolvedPct <= UNRESOLVED_CLIENTS_FIX_PCT
    return {
        key: 'clients',
        badge: isOk ? 'OK' : 'Fix',
        title: isOk
            ? `Clients resolved for ${formatPct(100 - unresolvedPct)}`
            : `${formatPct(unresolvedPct)} of calls from an unresolved client`,
        detail: isOk
            ? 'Resolved from the client name and the user agent.'
            : 'Those calls show as Other. Pass the client name through from your dispatcher.',
        link: isOk ? undefined : { to: DOCS_CLIENT_NAME, label: 'How to set it up' },
    }
}

function modelItem(modelRows: readonly MCPModelBreakdownItem[]): CoverageItem {
    const totalCalls = modelRows.reduce((sum, row) => sum + row.total_calls, 0)
    const unknownCalls = modelRows
        .filter((row) => row.model === 'Unknown')
        .reduce((sum, row) => sum + row.total_calls, 0)
    const knownPct = totalCalls > 0 ? ((totalCalls - unknownCalls) / totalCalls) * 100 : 0
    return {
        key: 'model',
        badge: 'Info',
        title: knownPct > 0 ? `Model known on ${formatPct(knownPct)}` : 'Model unknown',
        detail:
            knownPct > 0
                ? 'Reported by the agent itself, so it is not verified.'
                : 'No call reported a model. Agents send it only when they are asked to.',
    }
}

function missingCapabilityItem(hasMissingReports: boolean): CoverageItem {
    return {
        key: 'missing-capability',
        badge: hasMissingReports ? 'OK' : 'Info',
        title: 'Missing capability reporting',
        detail: hasMissingReports
            ? 'Agents are telling you which tools they wish you had.'
            : 'No reports in this range. If reportMissing is off, enable it so agents can tell you what is missing.',
        link: hasMissingReports
            ? { to: urls.mcpAnalyticsMissingCapabilities(), label: 'Read the reports' }
            : { to: DOCS_MISSING_CAPABILITY, label: 'How to set it up' },
    }
}

export function buildCoverageItems({
    summary,
    harnessRows,
    modelRows,
    hasMissingReports,
}: {
    summary: MCPOverviewSummary | null
    harnessRows: readonly MCPHarnessBreakdownItem[]
    modelRows: readonly MCPModelBreakdownItem[]
    hasMissingReports: boolean
}): CoverageItem[] {
    const anchoring = buildChecklist(overviewAsEarlyStats(summary)).find((item) => item.key === 'sessions')
    return [
        intentItem(summary),
        ...(anchoring ? [fromChecklistItem(anchoring)] : []),
        clientItem(harnessRows),
        modelItem(modelRows),
        missingCapabilityItem(hasMissingReports),
    ]
}
