import { MCPToolApprovalStateEnumApi } from '../generated/api.schemas'

const POLICY_STRICTNESS: Record<MCPToolApprovalStateEnumApi, number> = {
    approved: 0,
    needs_approval: 1,
    do_not_use: 2,
}

/** A member or agent may match the team ceiling or choose a stricter state. */
export function isPolicyStateAllowedByCeiling(
    state: MCPToolApprovalStateEnumApi,
    ceiling: MCPToolApprovalStateEnumApi | null
): boolean {
    return ceiling === null || POLICY_STRICTNESS[state] >= POLICY_STRICTNESS[ceiling]
}
