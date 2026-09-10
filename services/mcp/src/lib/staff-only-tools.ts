// Imported from the generated file rather than `@/lib/oauth-constants` (which
// re-exports it) so this module stays importable from plain Node — the constants
// module reaches `cloudflare:workers` via `@/lib/env`.
import { OAUTH_SCOPES_HIDDEN } from '@/lib/oauth-scopes.generated'

const HIDDEN_SCOPES = new Set<string>(OAUTH_SCOPES_HIDDEN)

/** A tool requiring an OAuth-hidden scope is a staff-only surface. */
export const isStaffOnlyTool = (requiredScopes: string[]): boolean =>
    requiredScopes.some((scope) => HIDDEN_SCOPES.has(scope))

/**
 * Hidden scopes must be explicitly minted on the key — a full-access `*` key
 * must not match, mirroring the backend's INTERNAL scope handling, which
 * rejects wildcard keys on staff endpoints.
 */
export const keyExplicitlyGrantsHiddenScopes = (requiredScopes: string[], keyScopes: string[]): boolean =>
    requiredScopes.every((scope) => !HIDDEN_SCOPES.has(scope) || keyScopes.includes(scope))

/**
 * Drop staff-only tools unless the key explicitly carries their hidden scope
 * AND the authed user is staff (the backend enforces `is_staff` on every call;
 * this keeps the tools out of customers' tool lists entirely). The staff
 * lookup needs `user:read` on the key and fails closed, hiding the tools
 * whenever staffness cannot be confirmed. The lookup only runs when a
 * staff-only tool would otherwise surface, so customer sessions never pay it.
 *
 * Tenant-scoped keys (scoped_teams/scoped_organizations) never surface staff
 * tools either: the staff endpoints reject scoped keys outright, so showing
 * the tools would only advertise calls that always 403.
 */
export async function filterStaffOnlyTools<T extends { scopes: string[] }>(
    tools: T[],
    key: { scopes: string[]; scoped_teams?: number[]; scoped_organizations?: string[] },
    getUser: () => Promise<{ is_staff?: boolean }>
): Promise<T[]> {
    const keyScopes = key.scopes
    const keyIsTenantScoped = (key.scoped_teams?.length ?? 0) > 0 || (key.scoped_organizations?.length ?? 0) > 0
    if (keyIsTenantScoped) {
        return tools.filter((tool) => !isStaffOnlyTool(tool.scopes))
    }

    let userIsStaff = false
    if (tools.some((tool) => isStaffOnlyTool(tool.scopes) && keyExplicitlyGrantsHiddenScopes(tool.scopes, keyScopes))) {
        try {
            userIsStaff = (await getUser()).is_staff === true
        } catch {
            userIsStaff = false
        }
    }

    return tools.filter(
        (tool) =>
            !isStaffOnlyTool(tool.scopes) || (keyExplicitlyGrantsHiddenScopes(tool.scopes, keyScopes) && userIsStaff)
    )
}
