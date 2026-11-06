import { LemonTag } from '@posthog/lemon-ui'

import type { MCPServiceAccountServerApi } from 'products/mcp_store/frontend/generated/api.schemas'

/**
 * Tags shown before the rest collapse into a count. `MAX_SCOUT_MCP_GATEWAY_SERVERS` lets a scout
 * hold 100 servers, so an unbounded header would push the row it summarizes off the screen.
 */
const MAX_SUMMARY_TAGS = 3

/**
 * What the scout may reach, for the collapsed header of the settings picker. The names come from
 * the team's shared servers, so a selected id whose share was withdrawn drops out, matching what a
 * run mounts.
 */
export function ScoutMcpServersSummary({
    loading,
    resolved,
    selectedServers,
}: {
    loading: boolean
    /** False when the shared-server lookup did not answer, so no selection can be read from it. */
    resolved: boolean
    selectedServers: MCPServiceAccountServerApi[]
}): JSX.Element | null {
    // "None" is a verdict about a resolved list. A failed lookup would otherwise report that the
    // scout reaches nothing while its runs still mount every server it holds.
    if (loading || !resolved) {
        return null
    }
    if (selectedServers.length === 0) {
        return <span className="text-[11.5px] text-muted">None</span>
    }
    const shown = selectedServers.slice(0, MAX_SUMMARY_TAGS)
    const hiddenCount = selectedServers.length - shown.length
    return (
        <>
            {shown.map((server) => (
                // A server name holds up to 200 characters, which would otherwise widen the header
                // past the row. The full name stays reachable on hover.
                <LemonTag key={server.id} size="small" type="option" className="max-w-32" title={server.name}>
                    <span className="min-w-0 truncate">{server.name}</span>
                </LemonTag>
            ))}
            {hiddenCount > 0 ? <span className="text-[11.5px] text-muted">+{hiddenCount} more</span> : null}
        </>
    )
}
