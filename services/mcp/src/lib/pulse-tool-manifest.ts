/**
 * The only PostHog MCP tools available to a staged Pulse sandbox.
 *
 * Pulse is an unattended capability. Its OAuth scopes are necessary API authorization, but
 * they are deliberately not the tool policy: several tools can share one read scope and a
 * later tool must not silently enter an existing sandbox. Keep this list explicit and
 * versioned. The scope posture only selects this manifest; it never expands it.
 */

const PULSE_READ_SCOPES_V1 = [
    'action:read',
    'alert:read',
    'annotation:read',
    'cohort:read',
    'dashboard:read',
    'data_catalog:read',
    'error_tracking:read',
    'event_definition:read',
    'experiment:read',
    'feature_flag:read',
    'insight:read',
    'metrics:read',
    'property_definition:read',
    'query:read',
    'subscription:read',
    'warehouse_objects:read',
    'warehouse_table:read',
    'warehouse_view:read',
    'web_analytics:read',
] as const

const PULSE_INTERNAL_SCOPES = ['internal_run:read', 'llm_gateway:read'] as const
const PULSE_EXPERIMENT_DRAFT_SCOPE = 'pulse_experiment_draft:write'

export const PULSE_ANALYSIS_TOOL_MANIFEST_V1 = [
    'action-get',
    'actions-get-all',
    'alert-get',
    'alerts-list',
    'annotation-retrieve',
    'annotations-list',
    'characterize-metric-anomaly',
    'cohorts-list',
    'cohorts-retrieve',
    'dashboard-get',
    'dashboard-insights-run',
    'dashboard-widget-catalog-list',
    'dashboard-widgets-run',
    'dashboards-get-all',
    'data-catalog-metric-run',
    'error-tracking-assignment-rules-list',
    'error-tracking-bypass-rules-list',
    'error-tracking-grouping-rules-list',
    'error-tracking-recommendations-list',
    'error-tracking-settings-get',
    'error-tracking-severity-rules-list',
    'error-tracking-suppression-rules-list',
    'error-tracking-symbol-sets-list',
    'error-tracking-symbol-sets-retrieve',
    'experiment-get',
    'experiment-get-all',
    'experiment-list',
    'experiment-results-get',
    'experiment-stats',
    'experiment-timeseries-results',
    'feature-flag-get-all',
    'feature-flag-get-definition',
    'feature-flag-get-definition-by-key',
    'feature-flags-bulk-keys-retrieve',
    'feature-flags-dependent-flags-retrieve',
    'feature-flags-evaluation-reasons-retrieve',
    'feature-flags-my-flags-retrieve',
    'feature-flags-status-retrieve',
    'insight-get',
    'insight-query',
    'insights-list',
    'insights-trending-retrieve',
    'managed-warehouse-metric-history-get',
    'managed-warehouse-monitoring-get',
    'metric-names-list',
    'query-error-tracking-issue',
    'query-error-tracking-issue-events',
    'query-error-tracking-issues-list',
    'query-funnel',
    'query-lifecycle',
    'query-metrics',
    'query-paths',
    'query-retention',
    'query-stickiness',
    'query-trends',
    'query-web-overview',
    'query-web-stats',
    'query-web-vitals',
    'pulse-outcome-replay-get',
    'pulse-public-research-create',
    'read-data-schema',
    'saved-query-column-annotations-list',
    'scheduled-changes-get',
    'scheduled-changes-list',
    'subscriptions-deliveries-list',
    'subscriptions-deliveries-retrieve',
    'subscriptions-list',
    'subscriptions-retrieve',
    'view-get',
    'view-list',
    'view-run-history',
    'web-analytics-weekly-digest',
] as const

export const PULSE_EXECUTION_TOOL_MANIFEST_V1 = [
    ...PULSE_ANALYSIS_TOOL_MANIFEST_V1,
    'experiment-pulse-draft-create',
] as const

function hasExactPulseScopePosture(scopes: readonly string[]): boolean {
    const granted = new Set(scopes)
    const allowed = new Set([...PULSE_READ_SCOPES_V1, ...PULSE_INTERNAL_SCOPES, PULSE_EXPERIMENT_DRAFT_SCOPE])

    return (
        PULSE_READ_SCOPES_V1.every((scope) => granted.has(scope)) &&
        PULSE_INTERNAL_SCOPES.every((scope) => granted.has(scope)) &&
        [...granted].every((scope) => allowed.has(scope))
    )
}

/**
 * Select a Pulse manifest from server-introspected OAuth scopes.
 *
 * `internal_run:read` is not user grantable. Requiring the complete, exact private posture
 * keeps a personal key or a broader sandbox token on the normal catalog, while a Pulse token
 * is denied every tool that is not named above.
 */
export function getPulseToolManifest(scopes: readonly string[]): readonly string[] | undefined {
    if (!hasExactPulseScopePosture(scopes)) {
        return undefined
    }
    return scopes.includes(PULSE_EXPERIMENT_DRAFT_SCOPE)
        ? PULSE_EXECUTION_TOOL_MANIFEST_V1
        : PULSE_ANALYSIS_TOOL_MANIFEST_V1
}
