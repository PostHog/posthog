import { MCPToolApprovalStateEnumApi } from '../generated/api.schemas'

const POLICY_STRICTNESS: Record<MCPToolApprovalStateEnumApi, number> = {
    approved: 0,
    needs_approval: 1,
    do_not_use: 2,
}

const DESTRUCTIVE_TOOL_TOKENS = new Set([
    'archive',
    'archived',
    'archives',
    'archiving',
    'ban',
    'banned',
    'banning',
    'bans',
    'cancel',
    'canceled',
    'canceling',
    'cancelled',
    'cancelling',
    'cancels',
    'delete',
    'deleted',
    'deletes',
    'deleting',
    'destroy',
    'destroyed',
    'destroying',
    'destroys',
    'drop',
    'dropped',
    'dropping',
    'drops',
    'erase',
    'erased',
    'erases',
    'erasing',
    'overwrite',
    'overwritten',
    'overwrites',
    'overwriting',
    'overwrote',
    'purge',
    'purged',
    'purges',
    'purging',
    'remove',
    'removed',
    'removes',
    'removing',
    'reset',
    'resets',
    'resetting',
    'revoke',
    'revoked',
    'revokes',
    'revoking',
    'suspend',
    'suspended',
    'suspending',
    'suspends',
    'terminate',
    'terminated',
    'terminates',
    'terminating',
    'truncate',
    'truncated',
    'truncates',
    'truncating',
    'wipe',
    'wiped',
    'wipes',
    'wiping',
])

function isDestructiveToolName(toolName: string): boolean {
    const tokens = toolName
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .toLowerCase()
        .split(/[^a-z0-9]+/)
        .filter(Boolean)
    return tokens.some((token) => DESTRUCTIVE_TOOL_TOKENS.has(token))
}

export function defaultAgentGrantPolicy(
    toolName: string,
    teamState: MCPToolApprovalStateEnumApi | null = null,
    isDestructive?: boolean
): 'approved' | 'do_not_use' {
    const defaultState = (isDestructive ?? isDestructiveToolName(toolName)) ? 'do_not_use' : 'approved'
    return isPolicyStateAllowedByCeiling(defaultState, teamState) ? defaultState : 'do_not_use'
}

/** A member or agent may match the team ceiling or choose a stricter state. */
export function isPolicyStateAllowedByCeiling(
    state: MCPToolApprovalStateEnumApi,
    ceiling: MCPToolApprovalStateEnumApi | null
): boolean {
    return ceiling === null || POLICY_STRICTNESS[state] >= POLICY_STRICTNESS[ceiling]
}
