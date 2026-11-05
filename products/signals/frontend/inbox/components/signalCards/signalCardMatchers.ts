import type { SignalNode } from 'scenes/debug/signals/types'

import type {
    AnalyticsAnomalyInvestigationSignalExtraApi,
    EndpointExecutionFailedSignalExtraApi,
    ErrorTrackingSignalExtraApi,
    GithubIssueSignalExtraApi,
    HealthCheckSignalExtraApi,
    LinearIssueSignalExtraApi,
    LlmEvalReportSignalExtraApi,
    LlmEvalSignalExtraApi,
    LogsAlertStateChangeSignalExtraApi,
    PgAnalyzeIssueSignalExtraApi,
    ReplayVisionScannerFindingSignalExtraApi,
    SessionProblemSignalExtraApi,
    SignalsScoutSignalExtraApi,
    ZendeskTicketSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'
import { SignalSourceProduct } from 'products/signals/frontend/inbox/types'

/** Narrows a signal's `extra` to the error tracking shape (a string `fingerprint`). */
export function isErrorTrackingExtra(value: unknown): value is Record<string, unknown> & ErrorTrackingSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.fingerprint === 'string'
}

/** Narrows a raw `extra` payload to the live session-problem shape. */
export function isSessionProblemExtra(value: unknown): value is Record<string, unknown> & SessionProblemSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.session_id === 'string' && 'problem_type' in extra
}

/** Narrows a raw `extra` payload to the replay-vision scanner-finding shape. */
export function isScannerFindingExtra(
    value: unknown
): value is Record<string, unknown> & ReplayVisionScannerFindingSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.session_id === 'string' && typeof extra.problem_type === 'string' && 'confidence' in extra
}

export function isLlmEvalTraceExtra(value: unknown): value is Record<string, unknown> & LlmEvalSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'evaluation_id' in extra && 'trace_id' in extra
}

export function isLlmEvalReportExtra(value: unknown): value is Record<string, unknown> & LlmEvalReportSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'evaluation_id' in extra && 'report_run_id' in extra
}

/**
 * Health-check signals are PostHog-native instrumentation issues. They always carry a `kind`,
 * a `severity`, and an `issue_id`, which together distinguish them from other native sources.
 */
export function isHealthCheckExtra(value: unknown): value is Record<string, unknown> & HealthCheckSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'kind' in extra && 'severity' in extra && 'issue_id' in extra
}

/** Narrows a signal's `extra` to the endpoint execution failure shape. */
export function isEndpointExecutionFailedExtra(
    value: unknown
): value is Record<string, unknown> & EndpointExecutionFailedSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.endpoint_name === 'string' && typeof extra.error_class === 'string'
}

export type RepoWorkflowExtra = Record<string, unknown> & {
    repo_owner: string
    repo_name: string
    workflow_name: string
}

/** Every engineering_analytics CI signal carries repo + workflow identity; the rest is per-type. */
export function hasRepoWorkflow(value: unknown): value is RepoWorkflowExtra {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return (
        typeof extra.repo_owner === 'string' &&
        typeof extra.repo_name === 'string' &&
        typeof extra.workflow_name === 'string'
    )
}

/** Narrows a signal's `extra` to the logs alert state-change shape. */
export function isLogsAlertStateChangeExtra(
    value: unknown
): value is Record<string, unknown> & LogsAlertStateChangeSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return (
        typeof extra.alert_id === 'string' &&
        (extra.action === 'firing' || extra.action === 'broken') &&
        'threshold_count' in extra
    )
}

/** Narrows a signal's `extra` to the product-analytics anomaly-investigation shape. */
export function isAnalyticsAnomalyInvestigationExtra(
    value: unknown
): value is Record<string, unknown> & AnalyticsAnomalyInvestigationSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.alert_id === 'string' && typeof extra.insight_id === 'string'
}

/** Narrows a raw `extra` payload to the live Signals scout shape. */
export function isSignalsScoutExtra(value: unknown): value is Record<string, unknown> & SignalsScoutSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return Array.isArray(extra.evidence) && typeof extra.skill_name === 'string'
}

/** Narrows a signal's `extra` to a GitHub issue payload. */
export function isGithubIssueExtra(value: unknown): value is Record<string, unknown> & GithubIssueSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'html_url' in extra && 'number' in extra
}

/**
 * Linear has `url` + `priority` + `number`, but unlike GitHub it carries no `html_url`.
 * Requiring `identifier` and `priority_label` keeps this narrow enough not to match other issue sources.
 */
export function isLinearIssueExtra(value: unknown): value is Record<string, unknown> & LinearIssueSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'identifier' in extra && 'priority_label' in extra && typeof extra.url === 'string'
}

/** Guard for Zendesk ticket extras. Keys on `status` + `tags` so it doesn't collide with Linear, which also carries `url` + `priority`. */
export function isZendeskTicketExtra(value: unknown): value is Record<string, unknown> & ZendeskTicketSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.url === 'string' && 'status' in extra && 'tags' in extra
}

/** Narrows a signal's `extra` to a pganalyze issue payload. */
export function isPgAnalyzeExtra(value: unknown): value is Record<string, unknown> & PgAnalyzeIssueSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'references' in extra && Array.isArray(extra.references) && 'synced_at' in extra
}

/**
 * Ordered list of signal-card matchers, shared by the Lemon and quill registries. The first entry whose
 * `matches` returns true picks the card; no match falls back to the generic card. Every entry gates on
 * `source_product`, so entries are mutually exclusive and order is not load-bearing — but keep
 * richer/more-specific variants first as a safety net.
 */
export const SIGNAL_CARD_MATCHERS = [
    // PostHog products with live embeds
    {
        key: 'error_tracking',
        matches: (signal: SignalNode) =>
            signal.source_product === 'error_tracking' && isErrorTrackingExtra(signal.extra),
    },
    {
        key: 'session_replay',
        matches: (signal: SignalNode) =>
            signal.source_product === 'session_replay' && isSessionProblemExtra(signal.extra),
    },
    {
        key: 'replay_vision',
        matches: (signal: SignalNode) =>
            signal.source_product === 'replay_vision' && isScannerFindingExtra(signal.extra),
    },
    // LLM analytics: report variant first (mutually exclusive guards, but explicit)
    {
        key: 'llm_analytics:evaluation_report',
        matches: (signal: SignalNode) =>
            signal.source_product === 'llm_analytics' && isLlmEvalReportExtra(signal.extra),
    },
    {
        key: 'llm_analytics:evaluation',
        matches: (signal: SignalNode) => signal.source_product === 'llm_analytics' && isLlmEvalTraceExtra(signal.extra),
    },
    // Other PostHog-native products
    {
        key: 'health_checks',
        matches: (signal: SignalNode) => signal.source_product === 'health_checks' && isHealthCheckExtra(signal.extra),
    },
    {
        key: 'conversations',
        matches: (signal: SignalNode) => signal.source_product === 'conversations' && signal.source_type === 'ticket',
    },
    {
        key: 'endpoints',
        matches: (signal: SignalNode) =>
            signal.source_product === 'endpoints' && isEndpointExecutionFailedExtra(signal.extra),
    },
    {
        key: 'engineering_analytics',
        matches: (signal: SignalNode) =>
            signal.source_product === SignalSourceProduct.EngineeringAnalytics && hasRepoWorkflow(signal.extra),
    },
    {
        key: 'logs',
        matches: (signal: SignalNode) => signal.source_product === 'logs' && isLogsAlertStateChangeExtra(signal.extra),
    },
    {
        key: 'analytics',
        matches: (signal: SignalNode) =>
            signal.source_product === 'analytics' && isAnalyticsAnomalyInvestigationExtra(signal.extra),
    },
    {
        key: 'signals_scout',
        matches: (signal: SignalNode) => signal.source_product === 'signals_scout' && isSignalsScoutExtra(signal.extra),
    },
    // External sources
    {
        key: 'github',
        matches: (signal: SignalNode) => signal.source_product === 'github' && isGithubIssueExtra(signal.extra),
    },
    {
        key: 'linear',
        matches: (signal: SignalNode) => signal.source_product === 'linear' && isLinearIssueExtra(signal.extra),
    },
    {
        key: 'zendesk',
        matches: (signal: SignalNode) => signal.source_product === 'zendesk' && isZendeskTicketExtra(signal.extra),
    },
    {
        key: 'pganalyze',
        matches: (signal: SignalNode) => signal.source_product === 'pganalyze' && isPgAnalyzeExtra(signal.extra),
    },
] as const

/** Stable identifier for the source/variant a card renders. Each registry maps every key to a component. */
export type SignalCardKey = (typeof SIGNAL_CARD_MATCHERS)[number]['key']

/** The key of the first matching card, or null when the signal should use the generic fallback. */
export function matchSignalCard(signal: SignalNode): SignalCardKey | null {
    return SIGNAL_CARD_MATCHERS.find((matcher) => matcher.matches(signal))?.key ?? null
}
