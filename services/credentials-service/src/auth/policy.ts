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

export type IntegrationRole = 'web' | 'worker' | 'resolver'

export const ROLE_OPS: Readonly<Record<IntegrationRole, readonly IntegrationOp[]>> = {
    web: INTEGRATION_OPS,
    worker: ['read', 'resolve', 'write', 'refresh', 'list_across_teams'],
    resolver: ['resolve'],
}

/** Deployments matched by their exact name. */
const EXACT: Readonly<Record<string, IntegrationRole>> = {
    'posthog-django': 'web',
}

/**
 * Deployment families: the name itself, or the name followed by `-` and anything. A family
 * adds no attack surface, because whoever can add a signing key can also choose its name.
 * The web role is never given to a family.
 */
const FAMILIES: readonly (readonly [string, Exclude<IntegrationRole, 'web'>])[] = [
    ['temporal-worker', 'worker'],
    ['posthog-celery', 'worker'],
    ['cdp', 'resolver'],
    ['ingestion', 'resolver'],
    ['push-api', 'resolver'],
]

export function roleFor(deployment: string): IntegrationRole | null {
    const exact = EXACT[deployment]
    if (exact) {
        return exact
    }
    for (const [family, role] of FAMILIES) {
        if (deployment === family || deployment.startsWith(`${family}-`)) {
            return role
        }
    }
    return null
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
