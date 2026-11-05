import { combineUrl } from 'kea-router'

import { Dayjs, dayjs } from 'lib/dayjs'
import { scoutDisplayName, signalCardSourceLine } from 'lib/signals/signalCardSourceLine'
import { reverseColonDelimitedDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'
import { isTrustedPostHogUrl } from 'lib/utils/trustedUrl'
import type { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import type { LLMTrace } from '~/queries/schema/schema-general'

import { formatLLMCost, formatLLMLatency, formatTokens } from 'products/ai_observability/frontend/utils'
import type {
    AnalyticsAnomalyInvestigationSignalExtraApi,
    ConversationsTicketImageApi,
    ConversationsTicketSignalExtraApi,
    EndpointExecutionFailedSignalExtraApi,
    EngineeringAnalyticsCIBrokenDefaultBranchSignalExtraApi,
    EngineeringAnalyticsCIDurationRegressionSignalExtraApi,
    EngineeringAnalyticsCIFlakyCheckSignalExtraApi,
    HealthCheckSignalExtraApi,
    LinearIssueSignalExtraApi,
    PgAnalyzeIssueReferenceApi,
    PgAnalyzeIssueSignalExtraApi,
    SignalsScoutSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'
import { SignalSourceType } from 'products/signals/frontend/inbox/types'
import { safeHttpUrl } from 'products/signals/frontend/inbox/utils/reportPresentation'

import type {
    InboxErrorTrackingIssueLogicProps,
    InboxErrorTrackingIssueSourceType,
} from './inboxErrorTrackingIssueLogic'

/**
 * Non-UI parsing shared by the Lemon and quill signal cards, so the two views can only differ in
 * markup. Per-source sections follow the card they serve.
 */

// ── Card header ──────────────────────────────────────────────────────────────────

export interface SignalCardSource {
    /** Plain-text source line, also the hover title. */
    sourceLine: string
    /** Set for a scout-authored finding whose name can be linked to the scout's detail page. */
    scoutSkillName: string | null
}

export function signalCardSource(signal: SignalNode): SignalCardSource {
    // Scout-authored findings link the scout's name to its detail page; everything else stays plain text.
    const scoutSkillName =
        signal.source_product === 'signals_scout'
            ? (signal.extra as { skill_name?: unknown } | undefined)?.skill_name
            : undefined
    const scoutName = typeof scoutSkillName === 'string' ? scoutDisplayName(scoutSkillName) : null
    return {
        sourceLine: scoutName ? `Scout · ${scoutName}` : signalCardSourceLine(signal),
        scoutSkillName: scoutName && typeof scoutSkillName === 'string' ? scoutSkillName : null,
    }
}

// ── Recordings (session replay, replay vision) ───────────────────────────────────

/** "10 chars…" form of a distinct id for the dot-separated meta line. */
export function shortDistinctId(distinctId: string): string {
    return `${distinctId.slice(0, 10)}…`
}

/** "3m active / 7m total", either half alone, or null when neither duration is known. */
export function recordingDurationSummary(
    activeDuration: string | undefined,
    totalDuration: string | undefined
): string | null {
    if (!activeDuration && !totalDuration) {
        return null
    }
    return [activeDuration ? `${activeDuration} active` : null, totalDuration ? `${totalDuration} total` : null]
        .filter(Boolean)
        .join(' / ')
}

/** How many timeline events to show before collapsing the rest behind a toggle. */
export const TIMELINE_PREVIEW_COUNT = 4

/**
 * Segment and event times arrive as recording-relative offsets (`MM:SS` / `HH:MM:SS`), not datetimes.
 * Combine the offset with the session start to get an absolute timestamp the player can seek to.
 */
export function recordingSeekTime(sessionStartTime: string | undefined, offset: string | undefined): Dayjs | undefined {
    const offsetSeconds = reverseColonDelimitedDuration(offset)
    if (!sessionStartTime || offsetSeconds === null) {
        return undefined
    }
    return dayjs(sessionStartTime).add(offsetSeconds, 'second')
}

/**
 * Findings carry `start_time`/`end_time` as second offsets from the recording start, and
 * `recording_start_time` as an absolute datetime. Combine them to get an instant the player can seek to.
 */
export function findingSeekTime(
    recordingStartTime: string | null | undefined,
    offsetSeconds: number
): Dayjs | undefined {
    if (!recordingStartTime) {
        return undefined
    }
    return dayjs(recordingStartTime).add(offsetSeconds, 'second')
}

// ── Error tracking ───────────────────────────────────────────────────────────────

function errorTrackingSourceType(sourceType: string): InboxErrorTrackingIssueSourceType {
    return sourceType === 'issue_reopened' || sourceType === 'issue_spiking' ? sourceType : 'issue_created'
}

export function errorTrackingIssueLogicProps(
    signal: SignalNode,
    fingerprint: string
): InboxErrorTrackingIssueLogicProps {
    return {
        issueId: signal.source_id,
        fingerprint,
        sourceType: errorTrackingSourceType(signal.source_type),
    }
}

// ── Health checks ────────────────────────────────────────────────────────────────

/** The card's markdown body: the signal content, or the summary when there is no content. */
export function healthCheckBodyText(signal: SignalNode, extra: HealthCheckSignalExtraApi): string {
    // Avoid printing the summary twice when content already equals it.
    return signal.content || extra.summary || ''
}

function capitalize(value: string): string {
    return value.length > 0 ? value.charAt(0).toUpperCase() + value.slice(1) : value
}

/** Turn a snake_case payload key into a readable label, e.g. `current_version` → `Current version`. */
function humanizeKey(key: string): string {
    return capitalize(key.replace(/_/g, ' '))
}

function isPrimitive(value: unknown): value is string | number | boolean {
    return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
}

/** Format a single primitive value for display (booleans become Yes/No). */
function formatPrimitive(value: string | number | boolean): string {
    if (typeof value === 'boolean') {
        return value ? 'Yes' : 'No'
    }
    return String(value)
}

/**
 * Format a payload value into a display string, or return null to omit it.
 * Nested objects and arrays of objects are omitted to avoid rendering "[object Object]".
 */
function formatPayloadValue(value: unknown): string | null {
    if (isPrimitive(value)) {
        return formatPrimitive(value)
    }
    if (Array.isArray(value)) {
        const primitives = value.filter(isPrimitive)
        if (primitives.length !== value.length || primitives.length === 0) {
            return null
        }
        const formatted = primitives.map(formatPrimitive)
        if (formatted.length > 5) {
            return `${formatted.slice(0, 5).join(', ')} +${formatted.length - 5} more`
        }
        return formatted.join(', ')
    }
    return null
}

/** Readable key-value rows over an `extra.payload`. Skips `reason` (shown as the summary). */
function payloadRows(payload: Record<string, unknown>): { key: string; label: string; value: string }[] {
    return Object.entries(payload)
        .filter(([key]) => key !== 'reason')
        .map(([key, value]) => ({ key, label: humanizeKey(key), value: formatPayloadValue(value) }))
        .filter((row): row is { key: string; label: string; value: string } => row.value !== null)
}

export type HealthCheckPayloadView =
    | { type: 'transition'; from: string; to: string }
    | { type: 'hosts'; hosts: string[] }
    | { type: 'rows'; rows: { key: string; label: string; value: string }[] }

/**
 * Picks how to show a health check's payload: `sdk_outdated` as one version or migration transition,
 * `partial_proxy` as host chips, and anything else (or a payload missing those fields) as key-value rows.
 */
export function healthCheckPayloadView(kind: string, payload: Record<string, unknown>): HealthCheckPayloadView {
    const rows: HealthCheckPayloadView = { type: 'rows', rows: payloadRows(payload) }

    if (kind === 'sdk_outdated') {
        const migrationTarget = payload.migration_target
        if (typeof migrationTarget === 'string') {
            const migrationSource = payload.migration_source
            if (typeof migrationSource !== 'string') {
                return rows
            }
            return { type: 'transition', from: formatPrimitive(migrationSource), to: formatPrimitive(migrationTarget) }
        }
        const current = payload.current_version
        const latest = payload.latest_version
        if (!isPrimitive(current) || !isPrimitive(latest)) {
            return rows
        }
        return { type: 'transition', from: formatPrimitive(current), to: formatPrimitive(latest) }
    }

    if (kind === 'partial_proxy') {
        const hosts = Array.isArray(payload.unproxied_hosts) ? payload.unproxied_hosts.filter(isPrimitive) : []
        if (hosts.length === 0) {
            return rows
        }
        return { type: 'hosts', hosts: hosts.map(formatPrimitive) }
    }

    return rows
}

// ── Conversations tickets ────────────────────────────────────────────────────────

/** Every field is optional so that evidence stored before the emitter carried it still renders. */
export type TicketExtra = Partial<ConversationsTicketSignalExtraApi>

export function ticketExtra(value: unknown): TicketExtra {
    return typeof value === 'object' && value !== null ? (value as TicketExtra) : {}
}

/** How many attachment thumbnails to show before pointing at the ticket for the rest. */
export const IMAGE_PREVIEW_COUNT = 4

export interface TicketImageLink {
    href: string
    /** Only an image PostHog serves loads inline; any other host is a click-to-open tile. */
    trusted: boolean
    label: string
    title: string | undefined
}

/**
 * The URL comes from ticket rich content, which is not origin-validated, and an inline `<img>` makes every
 * viewer's browser fetch it on render. Null when the URL is not a safe http(s) link at all.
 */
export function ticketImageLink(image: ConversationsTicketImageApi): TicketImageLink | null {
    const trusted = isTrustedPostHogUrl(image.url)
    const href = trusted ? image.url : safeHttpUrl(image.url)
    if (!href) {
        return null
    }
    return {
        href,
        trusted,
        label: image.author ? `Attachment from ${image.author}` : 'Ticket attachment',
        title: image.author ? `Attached by ${image.author}` : undefined,
    }
}

// ── Endpoints ────────────────────────────────────────────────────────────────────

export function endpointExecutionLinks(extra: EndpointExecutionFailedSignalExtraApi): {
    endpointUrl: string
    logsUrl: string
} {
    const endpointUrl = urls.endpoint(extra.endpoint_name, extra.endpoint_version ?? undefined)
    return { endpointUrl, logsUrl: combineUrl(endpointUrl, { tab: 'logs' }).url }
}

// ── Engineering analytics ────────────────────────────────────────────────────────

/** The headline metric line, switched on the CI signal variant. */
export function engineeringMetricLine(signal: SignalNode): string | null {
    const extra = signal.extra
    switch (signal.source_type) {
        case SignalSourceType.CiFlakyCheck: {
            const e = extra as Record<string, unknown> & EngineeringAnalyticsCIFlakyCheckSignalExtraApi
            return `Flaky · ${e.job_name} · ${e.flaky_count} runs in ${e.window_days}d`
        }
        case SignalSourceType.CiBrokenDefaultBranch: {
            const e = extra as Record<string, unknown> & EngineeringAnalyticsCIBrokenDefaultBranchSignalExtraApi
            return `${e.branch} · ${percentage(e.conclusive_success_rate, 0)} pass`
        }
        case SignalSourceType.CiDurationRegression: {
            const e = extra as Record<string, unknown> & EngineeringAnalyticsCIDurationRegressionSignalExtraApi
            return `p95 +${percentage(e.pct_increase, 0)}`
        }
        default:
            return null
    }
}

// ── LLM analytics ────────────────────────────────────────────────────────────────

// Reduce an arbitrary input/output state payload to a short displayable string.
function stringifyState(state: unknown): string {
    if (state == null) {
        return ''
    }
    if (typeof state === 'string') {
        return state
    }
    try {
        return JSON.stringify(state)
    } catch {
        return ''
    }
}

/** 2-line preview text derived from the trace's input/output state. */
export function llmTracePreviewText(trace: LLMTrace): string {
    return [stringifyState(trace.inputState), stringifyState(trace.outputState)].filter(Boolean).join('\n').trim()
}

/** Latency, cost and token metrics of a loaded trace. Each metric is guarded — missing fields are skipped. */
export function llmTraceMetrics(trace: LLMTrace): string[] {
    const metrics: string[] = []
    if (typeof trace.totalLatency === 'number') {
        metrics.push(formatLLMLatency(trace.totalLatency))
    }
    if (typeof trace.totalCost === 'number') {
        metrics.push(formatLLMCost(trace.totalCost))
    }
    if (typeof trace.inputTokens === 'number' || typeof trace.outputTokens === 'number') {
        metrics.push(`${formatTokens(trace.inputTokens ?? 0)} → ${formatTokens(trace.outputTokens ?? 0)}`)
    }
    return metrics
}

// ── Logs alerts ──────────────────────────────────────────────────────────────────

/** Reads a string array off the loosely-typed filters bag, returning [] when absent or malformed. */
function readStringArray(filters: Record<string, unknown>, key: string): string[] {
    const value = filters[key]
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

export interface LogsAlertFilterSummary {
    serviceNames: string[]
    severityLevels: string[]
    filterGroupCount: number
}

/** Services, severities, and a count of the remaining conditions of the alert's log filters. */
export function logsAlertFilterSummary(filters: Record<string, unknown>): LogsAlertFilterSummary {
    const filterGroup = filters.filterGroup

    // Best-effort count of extra UniversalFilters conditions without fully expanding them.
    let filterGroupCount = 0
    if (filterGroup && typeof filterGroup === 'object') {
        const values = (filterGroup as { values?: unknown }).values
        if (Array.isArray(values)) {
            filterGroupCount = values.length
        }
    }

    return {
        serviceNames: readStringArray(filters, 'serviceNames'),
        severityLevels: readStringArray(filters, 'severityLevels'),
        filterGroupCount,
    }
}

// ── Product analytics anomalies ──────────────────────────────────────────────────

export function anomalyInsightLabel(extra: AnalyticsAnomalyInvestigationSignalExtraApi): string {
    return extra.insight_name || extra.insight_short_id || extra.insight_id
}

// ── Signals scouts ───────────────────────────────────────────────────────────────

/** How many evidence rows to show before collapsing the rest behind a toggle. */
export const EVIDENCE_PREVIEW_COUNT = 3

export function scoutHypothesis(signal: SignalNode, extra: SignalsScoutSignalExtraApi): string {
    return extra.hypothesis?.trim() || signal.content
}

/**
 * Deep link the run id straight to its Tasks run tab — only resolvable when the task id was
 * captured at emit time (absent on older emissions).
 */
export function scoutTaskRunUrl(extra: SignalsScoutSignalExtraApi): string | undefined {
    return extra.task_id ? combineUrl(urls.taskDetail(extra.task_id), { runId: extra.task_run_id }).url : undefined
}

/** Truncated form of a footer run/finding id. */
export function truncatedMonoId(value: string): string {
    return value.length > 12 ? `${value.slice(0, 12)}…` : value
}

// ── External sources ─────────────────────────────────────────────────────────────

export function linearIssueTitle(extra: LinearIssueSignalExtraApi): string {
    return extra.identifier || `#${extra.number}`
}

/** Strip Zendesk API artifacts so a raw API URL resolves to the user-facing ticket URL. */
export function cleanZendeskUrl(url: string): string {
    return url.replace('/api/v2', '').replace('.json', '')
}

export function pgAnalyzeVisibleReferences(extra: PgAnalyzeIssueSignalExtraApi): PgAnalyzeIssueReferenceApi[] {
    return extra.references.filter(
        (reference) => reference.name !== null || reference.url !== null || reference.queryText !== null
    )
}

/** The first reference URL that is a safe http(s) link, used as the card's link-out. */
export function pgAnalyzeExternalUrl(extra: PgAnalyzeIssueSignalExtraApi): string | undefined {
    return extra.references
        .map((reference) => (reference.url !== null ? safeHttpUrl(reference.url) : null))
        .find((url): url is string => url !== null)
}
