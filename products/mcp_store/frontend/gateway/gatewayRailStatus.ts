import { GatewayServerEntry } from './mcpGatewayLogic'

export type GatewayRailStatus =
    | 'connected'
    | 'pending_oauth'
    | 'needs_reauth'
    | 'self_disabled'
    | 'team_off'
    | 'revoked'

/** Folds a connected server's flags into the single status the rail shows.
 * Blockers outrank connection state: a revoked or team-disabled server is not
 * usable no matter what the personal connection says. */
export function gatewayRailStatus(server: GatewayServerEntry): GatewayRailStatus | null {
    const connection = server.your_connection
    if (!connection) {
        return null
    }
    if (server.is_revoked_for_you) {
        return 'revoked'
    }
    if (!server.is_team_enabled) {
        return 'team_off'
    }
    if (connection.pending_oauth) {
        return 'pending_oauth'
    }
    if (connection.needs_reauth) {
        return 'needs_reauth'
    }
    if (!connection.is_enabled) {
        return 'self_disabled'
    }
    return 'connected'
}
