// What each deployment may do with customer integrations. A request needs its operation in
// the token's `ops` claim AND in this policy for the deployment whose key verified the token.
// The token narrows one call; this file bounds what a stolen caller key can do.
//
// One entry per real deployment, matched by exact name, with its ops and the kinds it may
// touch. There is no prefix or family match and no default: a deployment this file does not
// name gets nothing. Each entry holds only the ops and kinds its code uses.

export const INTEGRATION_OPS = [
    'read',
    'write',
    'delete',
    'resolve',
    'refresh',
    'revoke',
    'mint',
    'oauth_exchange',
    'reverse_sync',
    'list_across_teams',
    'read_by_external_id',
    'write_by_external_id',
    'delete_by_external_id',
    'delete_owner',
] as const

export type IntegrationOp = (typeof INTEGRATION_OPS)[number]

/**
 * Operations that read or change rows of more than one team. A token that holds these holds
 * no other op and carries no `owner`. `reverse_sync` reads the changes feed of every team.
 * `delete_owner` is not one of them: it deletes the rows of
 * the token's owner.
 */
export const CROSS_TEAM_OPS = [
    'list_across_teams',
    'read_by_external_id',
    'write_by_external_id',
    'delete_by_external_id',
    'reverse_sync',
] as const satisfies readonly IntegrationOp[]

export type CrossTeamOp = (typeof CROSS_TEAM_OPS)[number]

/**
 * Operations that always act on one named ref, so a token that holds one must carry `refs`.
 * `read` and `write` act on one ref for a get or a patch too. There the route names the ref,
 * and the token must carry it (see `IntegrationGrant.authorize`).
 */
export const SINGLE_REF_OPS = ['delete', 'refresh', 'revoke', 'mint'] as const satisfies readonly IntegrationOp[]

/**
 * Any kind, source rows included. Only for a deployment whose code can touch any kind: web,
 * the reverse sync, the broad job runners, and the resolvers that load hog function inputs.
 */
export const ALL_KINDS = '*'

export type KindAllowlist = typeof ALL_KINDS | readonly string[]

export interface DeploymentPolicy {
    ops: readonly IntegrationOp[]
    kinds: KindAllowlist
    /**
     * May touch warehouse source rows: the typed-in credentials of a warehouse source, marked
     * by `config.warehouse_source_type` (posthog/integrations/source_kinds.py). There are about
     * a thousand such kinds and the warehouse registers them at startup, so no list here could
     * keep up. The route tells the auth layer when a row is a source row.
     */
    sourceRows?: boolean
    /**
     * Narrows the kinds for one op to a subset of `kinds`. An op without an entry here gets
     * all of `kinds`.
     */
    opKinds?: Readonly<Partial<Record<IntegrationOp, readonly string[]>>>
}

const WORKER_OPS = [
    'read',
    'resolve',
    'write',
    'refresh',
    'list_across_teams',
] as const satisfies readonly IntegrationOp[]

// The OAuth kinds that warehouse sources connect with (`SourceFieldOauthConfig` in
// products/warehouse_sources) and the kinds of warehouse destinations
// (products/warehouse_sources/backend/presentation/views/external_data_destination.py).
const WAREHOUSE_KINDS = [
    'apple-ads',
    'aws-redshift',
    'aws-s3',
    'azure-blob',
    'bing-ads',
    'databricks',
    'github',
    'google-ads',
    'google-analytics',
    'google-cloud-service-account',
    'google-search-console',
    'google-sheets',
    'helpscout',
    'hubspot',
    'instagram',
    'intercom',
    'linear',
    'linkedin-ads',
    'meta-ads',
    'pardot',
    'pinterest-ads',
    'postgresql',
    'reddit-ads',
    'resend',
    's3-compatible',
    'salesforce',
    'snapchat',
    'snowflake',
    'stripe',
    'tiktok-ads',
    'twitter-ads',
    'youtube-analytics',
] as const

// BATCH_EXPORT_INTEGRATION_KINDS (products/batch_exports/backend/facade/enums.py).
const BATCH_EXPORT_KINDS = [
    'aws-redshift',
    'aws-s3',
    'azure-blob',
    'databricks',
    'google-cloud-service-account',
    'postgresql',
    's3-compatible',
    'snowflake',
] as const

// The GitHub App reads that mint installation tokens (`GitHubIntegration`).
const GITHUB_APP_OPS = ['read', 'resolve', 'refresh', 'mint'] as const satisfies readonly IntegrationOp[]

// Callers that read, resolve and mint for GitHub but never refresh a token themselves.
const GITHUB_READ_OPS = ['read', 'resolve', 'mint'] as const satisfies readonly IntegrationOp[]

const RESOLVE_ANY_KIND: DeploymentPolicy = { ops: ['resolve'], kinds: ALL_KINDS }

/**
 * Every deployment that may call the integrations routes. The names are the `apps/<name>`
 * charts in PostHog/charts, the same names as the `<deployment>.pub` files.
 */
const TABLE: Record<string, DeploymentPolicy> = {
    // Web Django: every op but the changes feed. The web-two, frontdoor and streaming pools
    // sign with this key.
    'posthog-web-django': { ops: INTEGRATION_OPS.filter((op) => op !== 'reverse_sync'), kinds: ALL_KINDS },
    // The dedicated Celery queue that copies service rows back to Django during the migration.
    // The changes feed is the one route that returns plaintext in bulk, so nothing else gets it.
    'posthog-integrations-reverse-sync': { ops: ['reverse_sync'], kinds: ALL_KINDS },

    // Celery, admin Django and the general-purpose Temporal worker run sweeps and jobs over
    // every OAuth kind (posthog/tasks/integrations.py) and many others.
    'posthog-worker-django': { ops: WORKER_OPS, kinds: ALL_KINDS },
    'posthog-admin-django': { ops: WORKER_OPS, kinds: ALL_KINDS },
    'temporal-worker-general-purpose': { ops: WORKER_OPS, kinds: ALL_KINDS },
    // HogQL `system.integrations` lists every kind of the team.
    'posthog-query-django': { ops: ['read'], kinds: ALL_KINDS },

    'temporal-worker-data-warehouse': { ops: WORKER_OPS, kinds: WAREHOUSE_KINDS, sourceRows: true },
    'warehouse-sources-load': { ops: WORKER_OPS, kinds: WAREHOUSE_KINDS, sourceRows: true },
    'temporal-worker-batch-exports': { ops: ['read', 'resolve', 'refresh'], kinds: BATCH_EXPORT_KINDS },

    // The tasks sandbox mints GitHub installation tokens, and the Slack app activities on the
    // same queue post to Slack (products/slack_app/backend/services/workspace_integrations.py).
    // Those activities count Slack workspaces by external id, so only the Slack kinds may use
    // the cross-team read.
    'temporal-worker-tasks-agent': {
        ops: [...GITHUB_APP_OPS, 'read_by_external_id'],
        kinds: ['github', 'slack', 'slack-posthog-code'],
        opKinds: { read_by_external_id: ['slack', 'slack-posthog-code'] },
    },
    // The tasks Max tools list and use GitHub repos (products/tasks/backend/max_tools.py).
    'temporal-worker-max-ai': { ops: GITHUB_READ_OPS, kinds: ['github'] },
    // products/wizard/backend/logic/workers/repository_publisher.py.
    'temporal-worker-wizard': { ops: GITHUB_READ_OPS, kinds: ['github'] },
    // Despite the name, this queue runs the signals, conversations, customer analytics,
    // business knowledge and review workflows (posthog/management/commands/start_temporal_worker.py).
    'temporal-worker-video-export': {
        ops: GITHUB_APP_OPS,
        kinds: ['github', 'gitlab', 'google-calendar', 'jira', 'linear', 'slack'],
    },
    // temporal-worker-health-check and temporal-worker-stamphog read no integration: no entry.

    // CDP. A hog function input can name an integration of any kind
    // (nodejs/src/cdp/services/hog-inputs.service.ts).
    'cdp-api': RESOLVE_ANY_KIND,
    'cdp-api-batch-exports': RESOLVE_ANY_KIND,
    'cdp-api-push': RESOLVE_ANY_KIND,
    'cdp-api-warehouse-webhooks': RESOLVE_ANY_KIND,
    'cdp-api-webhooks': RESOLVE_ANY_KIND,
    'cdp-cyclotron-worker-batch-resolve': RESOLVE_ANY_KIND,
    'cdp-cyclotron-worker-email': RESOLVE_ANY_KIND,
    'cdp-cyclotron-worker-hog-kafka': RESOLVE_ANY_KIND,
    'cdp-cyclotron-worker-hogflows-pg': RESOLVE_ANY_KIND,
    'cdp-cyclotron-worker-hogoverflow-kafka': RESOLVE_ANY_KIND,
    'cdp-data-warehouse-events-consumer': RESOLVE_ANY_KIND,
    'cdp-events-consumer': RESOLVE_ANY_KIND,
    'cdp-internal-events-consumer': RESOLVE_ANY_KIND,
    'cdp-legacy-events-consumer': RESOLVE_ANY_KIND,
    'cdp-realtime-only-events-consumer': RESOLVE_ANY_KIND,

    // Ingestion lanes run hog transformations, which load integration inputs the same way
    // (nodejs/src/servers/ingestion-general-server.ts, error-tracking-server.ts).
    'ingestion-ai-main': RESOLVE_ANY_KIND,
    'ingestion-ai-overflow': RESOLVE_ANY_KIND,
    'ingestion-analytics-async': RESOLVE_ANY_KIND,
    'ingestion-analytics-historical': RESOLVE_ANY_KIND,
    'ingestion-analytics-main': RESOLVE_ANY_KIND,
    'ingestion-analytics-overflow': RESOLVE_ANY_KIND,
    'ingestion-analytics-team2': RESOLVE_ANY_KIND,
    'ingestion-analytics-turbo': RESOLVE_ANY_KIND,
    'ingestion-clientwarnings-main': RESOLVE_ANY_KIND,
    'ingestion-errortracking-main': RESOLVE_ANY_KIND,
    'ingestion-errortracking-overflow': RESOLVE_ANY_KIND,
    'ingestion-heatmaps-main': RESOLVE_ANY_KIND,
}

export const POLICY: Readonly<Record<string, Readonly<DeploymentPolicy>>> = Object.freeze(TABLE)

/** The policy for `deployment`, or null when it has none. */
export function policyFor(deployment: string): DeploymentPolicy | null {
    return Object.prototype.hasOwnProperty.call(POLICY, deployment) ? (POLICY[deployment] ?? null) : null
}

export function deploymentAllows(deployment: string, op: IntegrationOp): boolean {
    return policyFor(deployment)?.ops.includes(op) ?? false
}

export function isCrossTeamOp(op: IntegrationOp): op is CrossTeamOp {
    return (CROSS_TEAM_OPS as readonly IntegrationOp[]).includes(op)
}

export function isIntegrationOp(value: unknown): value is IntegrationOp {
    return typeof value === 'string' && (INTEGRATION_OPS as readonly string[]).includes(value)
}
