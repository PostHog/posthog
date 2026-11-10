// What each deployment may do with customer integrations. A request needs its operation in
// the token's `ops` claim AND in this policy for the deployment whose key verified the token.
// The token narrows one call; this file bounds what a stolen signing key can do.
//
// Deployment names are the ones `registry.ts` derives from `__CALLER_KEY_<DEPLOYMENT>`
// entries. A deployment this file does not name gets no operation at all.

export const INTEGRATION_OPS = [
    'read',
    'write',
    'delete',
    'resolve',
    'refresh',
    'revoke',
    'mint',
    'oauth_exchange',
    'changes',
    'list_across_teams',
    'read_by_external_id',
    'write_by_external_id',
    'delete_by_external_id',
    'delete_owner',
] as const

export type IntegrationOp = (typeof INTEGRATION_OPS)[number]

/**
 * Operations that read or change rows of more than one team. A token that holds only these
 * may omit `owner`. `delete_owner` is not one of them: it deletes the rows of the token's owner.
 */
export const CROSS_TEAM_OPS = [
    'list_across_teams',
    'read_by_external_id',
    'write_by_external_id',
    'delete_by_external_id',
] as const satisfies readonly IntegrationOp[]

export type CrossTeamOp = (typeof CROSS_TEAM_OPS)[number]

export type IntegrationRole = 'web' | 'worker' | 'temporal' | 'resolver'

const WORKER_OPS = [
    'read',
    'resolve',
    'write',
    'refresh',
    'list_across_teams',
] as const satisfies readonly IntegrationOp[]

export const ROLE_OPS: Readonly<Record<IntegrationRole, readonly IntegrationOp[]>> = {
    web: INTEGRATION_OPS,
    worker: WORKER_OPS,
    // The tasks sandbox mints GitHub installation tokens from Temporal.
    temporal: [...WORKER_OPS, 'mint'],
    resolver: ['resolve'],
}

/**
 * Every deployment that may call the service, matched by its exact name. There is no prefix
 * or family match: a new deployment gets nothing until it is listed here.
 * Names come from the `__CALLER_KEY_<DEPLOYMENT>` entries in PostHog/charts (`apps/<name>`).
 */
const ROLES: Readonly<Record<string, IntegrationRole>> = {
    // Web Django. The web-two, frontdoor and streaming pools sign with this key.
    'posthog-web-django': 'web',

    // Celery workers.
    'posthog-worker-django': 'worker',
    // Query Django refreshes ad-integration tokens. Admin Django holds a key of its own.
    'posthog-query-django': 'worker',
    'posthog-admin-django': 'worker',
    'warehouse-sources-load': 'worker',

    // Temporal workers that hold a caller key.
    'temporal-worker-batch-exports': 'temporal',
    'temporal-worker-data-warehouse': 'temporal',
    'temporal-worker-general-purpose': 'temporal',
    'temporal-worker-health-check': 'temporal',
    'temporal-worker-max-ai': 'temporal',
    'temporal-worker-stamphog': 'temporal',
    'temporal-worker-tasks-agent': 'temporal',
    'temporal-worker-video-export': 'temporal',
    'temporal-worker-wizard': 'temporal',

    // CDP.
    'cdp-api': 'resolver',
    'cdp-api-batch-exports': 'resolver',
    'cdp-api-push': 'resolver',
    'cdp-api-warehouse-webhooks': 'resolver',
    'cdp-api-webhooks': 'resolver',
    'cdp-cyclotron-worker-batch-resolve': 'resolver',
    'cdp-cyclotron-worker-email': 'resolver',
    'cdp-cyclotron-worker-hog-kafka': 'resolver',
    'cdp-cyclotron-worker-hogflows-pg': 'resolver',
    'cdp-cyclotron-worker-hogoverflow-kafka': 'resolver',
    'cdp-data-warehouse-events-consumer': 'resolver',
    'cdp-events-consumer': 'resolver',
    'cdp-internal-events-consumer': 'resolver',
    'cdp-legacy-events-consumer': 'resolver',
    'cdp-realtime-only-events-consumer': 'resolver',

    // Ingestion lanes that read integrations.
    'ingestion-ai-main': 'resolver',
    'ingestion-ai-overflow': 'resolver',
    'ingestion-analytics-async': 'resolver',
    'ingestion-analytics-historical': 'resolver',
    'ingestion-analytics-main': 'resolver',
    'ingestion-analytics-overflow': 'resolver',
    'ingestion-analytics-team2': 'resolver',
    'ingestion-analytics-turbo': 'resolver',
    'ingestion-clientwarnings-main': 'resolver',
    'ingestion-errortracking-main': 'resolver',
    'ingestion-errortracking-overflow': 'resolver',
    'ingestion-heatmaps-main': 'resolver',
}

export function roleFor(deployment: string): IntegrationRole | null {
    return Object.hasOwn(ROLES, deployment) ? ROLES[deployment] : null
}

export function deploymentAllows(deployment: string, op: IntegrationOp): boolean {
    const role = roleFor(deployment)
    return role !== null && ROLE_OPS[role].includes(op)
}

export function isCrossTeamOp(op: IntegrationOp): op is CrossTeamOp {
    return (CROSS_TEAM_OPS as readonly IntegrationOp[]).includes(op)
}

export function isIntegrationOp(value: unknown): value is IntegrationOp {
    return typeof value === 'string' && (INTEGRATION_OPS as readonly string[]).includes(value)
}
