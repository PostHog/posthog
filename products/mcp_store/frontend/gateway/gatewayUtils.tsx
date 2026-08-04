import { useActions, useValues } from 'kea'

import { IconCheck, IconShieldLock, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils/strings'

import { MCPToolApprovalStateEnumApi, UserBasicApi } from '../generated/api.schemas'
import { agentServerAccessKey, mcpGatewayLogic } from './mcpGatewayLogic'

/** ProfilePicture wants a UserBasicType-ish shape; the generated UserBasicApi's
 * `hedgehog_config` type isn't assignable, so pass the fields it actually reads. */
export function toProfileUser(user: UserBasicApi): { first_name?: string; last_name?: string; email: string } {
    return { first_name: user.first_name, last_name: user.last_name, email: user.email }
}

/** Attributes a grant backed by someone else's connection, so a member never reads
 * a teammate's share as their own. */
export function sharedByLabel(users: UserBasicApi[]): string | null {
    if (users.length === 0) {
        return null
    }
    const [first, ...rest] = users
    const name = fullName(first) || first.email
    if (rest.length === 0) {
        return `Shared by ${name}`
    }
    return `Shared by ${name} and ${rest.length} other${rest.length === 1 ? '' : 's'}`
}

/** Admin-only escape hatch: the share switch only ever controls the viewer's own
 * grant, so removing an agent's access for the whole project needs its own action.
 * It stays available to an admin who never connected the server themselves. */
export function RemoveAllSharesButton({
    accountId,
    accountName,
    serverId,
    serverName,
    shareCount,
}: {
    accountId: string
    accountName: string
    serverId: string
    serverName: string
    shareCount: number
}): JSX.Element | null {
    const { agentServerAccessLoadingKeys, isAdmin } = useValues(mcpGatewayLogic)
    const { removeAllAgentServerShares } = useActions(mcpGatewayLogic)

    if (!isAdmin || shareCount === 0) {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            status="danger"
            size="small"
            loading={agentServerAccessLoadingKeys.has(agentServerAccessKey(accountId, serverId))}
            onClick={() =>
                LemonDialog.open({
                    title: `Remove all shares of ${serverName}?`,
                    description: (
                        <div className="max-w-120">
                            {shareCount} {shareCount === 1 ? 'member has' : 'members have'} shared a {serverName}{' '}
                            connection with {accountName}. Removing them stops {accountName} using {serverName} for
                            everyone in this project, and clears its tool settings for this server.
                        </div>
                    ),
                    secondaryButton: { type: 'secondary', children: 'Cancel' },
                    primaryButton: {
                        type: 'primary',
                        status: 'danger',
                        children: 'Remove all shares',
                        onClick: () => removeAllAgentServerShares(accountId, serverId),
                    },
                })
            }
        >
            Remove all shares
        </LemonButton>
    )
}

export const POLICY_LABELS: Record<MCPToolApprovalStateEnumApi, string> = {
    approved: 'Always Allow',
    needs_approval: 'Needs Approval',
    do_not_use: 'Blocked',
}

export const POLICY_HINTS: Record<MCPToolApprovalStateEnumApi, string> = {
    approved: 'Runs without asking',
    needs_approval: 'Waits for a human to approve',
    do_not_use: 'Never allowed',
}

export const POLICY_OPTIONS: { value: MCPToolApprovalStateEnumApi; label: string; icon: JSX.Element }[] = [
    { value: 'approved', label: 'Always Allow', icon: <IconCheck /> },
    { value: 'needs_approval', label: 'Needs Approval', icon: <IconShieldLock /> },
    { value: 'do_not_use', label: 'Blocked', icon: <IconX /> },
]

/** Small colored summary of how many tools sit in each policy state. */
export function PolicySummary({ counts }: { counts: Record<MCPToolApprovalStateEnumApi, number> }): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1">
                <LemonBadge.Number count={counts.approved} status="success" showZero />
                <span className="text-secondary">Always Allow</span>
            </span>
            <span className="flex items-center gap-1">
                <LemonBadge.Number count={counts.needs_approval} status="warning" showZero />
                <span className="text-secondary">Needs Approval</span>
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
