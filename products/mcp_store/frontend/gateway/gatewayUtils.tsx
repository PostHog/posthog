import { IconCheck, IconShieldLock, IconX } from '@posthog/icons'
import { LemonBadge, LemonTag } from '@posthog/lemon-ui'

import { MCPToolApprovalStateEnumApi, UserBasicApi } from '../generated/api.schemas'

/** ProfilePicture wants a UserBasicType-ish shape; the generated UserBasicApi's
 * `hedgehog_config` type isn't assignable, so pass the fields it actually reads. */
export function toProfileUser(user: UserBasicApi): { first_name?: string; last_name?: string; email: string } {
    return { first_name: user.first_name, last_name: user.last_name, email: user.email }
}

export const POLICY_LABELS: Record<MCPToolApprovalStateEnumApi, string> = {
    approved: 'Auto-approved',
    needs_approval: 'Requires approval',
    do_not_use: 'Blocked',
}

export const POLICY_HINTS: Record<MCPToolApprovalStateEnumApi, string> = {
    approved: 'Runs without asking',
    needs_approval: 'Waits for a human to approve',
    do_not_use: 'Never allowed',
}

export const POLICY_OPTIONS: { value: MCPToolApprovalStateEnumApi; label: string; icon: JSX.Element }[] = [
    { value: 'approved', label: 'Auto-approved', icon: <IconCheck /> },
    { value: 'needs_approval', label: 'Requires approval', icon: <IconShieldLock /> },
    { value: 'do_not_use', label: 'Blocked', icon: <IconX /> },
]

/** Small colored summary of how many tools sit in each policy state. */
export function PolicySummary({ counts }: { counts: Record<MCPToolApprovalStateEnumApi, number> }): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1">
                <LemonBadge.Number count={counts.approved} status="success" showZero />
                <span className="text-secondary">auto</span>
            </span>
            <span className="flex items-center gap-1">
                <LemonBadge.Number count={counts.needs_approval} status="warning" showZero />
                <span className="text-secondary">approval</span>
            </span>
            <span className="flex items-center gap-1">
                <LemonBadge.Number count={counts.do_not_use} status="danger" showZero />
                <span className="text-secondary">blocked</span>
            </span>
        </div>
    )
}

export function DecisionTag({ decision }: { decision: string }): JSX.Element {
    switch (decision) {
        case 'auto':
            return <LemonTag type="success">Auto-approved</LemonTag>
        case 'approved':
            return <LemonTag type="completion">Approved</LemonTag>
        case 'pending':
            return <LemonTag type="warning">Awaiting approval</LemonTag>
        case 'blocked':
            return <LemonTag type="danger">Blocked</LemonTag>
        default:
            return <LemonTag>{decision}</LemonTag>
    }
}
