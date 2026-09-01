import { useActions, useValues } from 'kea'

import { IconCheck, IconShieldLock, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDialog, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils/strings'

import { MCPAgentGrantScopeEnumApi, MCPToolApprovalStateEnumApi, UserBasicApi } from '../generated/api.schemas'
import { AgentServerShare, agentServerAccessKey, mcpGatewayLogic } from './mcpGatewayLogic'

/** ProfilePicture wants a UserBasicType-ish shape; the generated UserBasicApi's
 * `hedgehog_config` type isn't assignable, so pass the fields it actually reads. */
export function toProfileUser(user: UserBasicApi): { first_name?: string; last_name?: string; email: string } {
    return { first_name: user.first_name, last_name: user.last_name, email: user.email }
}

function memberNames(users: UserBasicApi[]): string {
    const [first, ...rest] = users
    const name = fullName(first) || first.email
    if (rest.length === 0) {
        return name
    }
    return `${name} and ${rest.length} other${rest.length === 1 ? '' : 's'}`
}

/** Attributes grants backed by other members' connections, so a member never reads
 * a teammate's share as their own. Team shares take the line when both kinds exist,
 * because those are the ones that also back the viewer's own agent runs. */
export function sharedByOthersLabel(share: AgentServerShare): string | null {
    if (share.teamSharedByOthers.length > 0) {
        return `Shared to the team by ${memberNames(share.teamSharedByOthers)}`
    }
    if (share.sharedByOthers.length > 0) {
        return `Shared by ${memberNames(share.sharedByOthers)}`
    }
    return null
}

/** Whose connection an agent call rode, for audit rows. */
export function credentialOwnerLabel(owner: UserBasicApi, grantScope: string): string {
    const name = fullName(owner) || owner.email
    return grantScope === 'team' ? `via ${name}'s connection (team share)` : `via ${name}'s connection`
}

export const AGENT_GRANT_SCOPE_OPTIONS: { value: MCPAgentGrantScopeEnumApi; label: string; tooltip: string }[] = [
    {
        value: 'personal',
        label: 'Only me',
        tooltip: 'The agent uses your connection only when it runs for you.',
    },
    {
        value: 'team',
        label: 'Everyone in this project',
        tooltip:
            "The agent uses your connection for every run in this project, including runs nobody started. Teammates can't use the connection directly, but agents act through it on their runs too.",
    },
]

/** Scope picker for the viewer's own grant. Changing it re-sends the share with the
 * new scope, so it shares the share's in-flight key and cannot be double-submitted. */
export function AgentGrantScopeControl({
    accountId,
    serverId,
    scope,
}: {
    accountId: string
    serverId: string
    scope: MCPAgentGrantScopeEnumApi
}): JSX.Element {
    const { agentServerAccessLoadingKeys } = useValues(mcpGatewayLogic)
    const { setAgentServerAccess } = useActions(mcpGatewayLogic)
    const saving = agentServerAccessLoadingKeys.has(agentServerAccessKey(accountId, serverId))

    return (
        <LemonSegmentedButton
            size="xsmall"
            value={scope}
            options={AGENT_GRANT_SCOPE_OPTIONS}
            disabledReason={saving ? 'Saving your change' : undefined}
            onChange={(next) => setAgentServerAccess(accountId, serverId, true, next)}
        />
    )
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
    approved: 'Always allow',
    needs_approval: 'Needs approval',
    do_not_use: 'Blocked',
}

export const POLICY_HINTS: Record<MCPToolApprovalStateEnumApi, string> = {
    approved: 'Runs without asking',
    needs_approval: 'Waits for a human to approve',
    do_not_use: 'Never allowed',
}

export const POLICY_OPTIONS: { value: MCPToolApprovalStateEnumApi; label: string; icon: JSX.Element }[] = [
    { value: 'approved', label: 'Always allow', icon: <IconCheck /> },
    { value: 'needs_approval', label: 'Needs approval', icon: <IconShieldLock /> },
    { value: 'do_not_use', label: 'Blocked', icon: <IconX /> },
]

/** Small colored summary of how many tools sit in each policy state. */
export function PolicySummary({ counts }: { counts: Record<MCPToolApprovalStateEnumApi, number> }): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1">
                <LemonBadge.Number count={counts.approved} status="success" showZero />
                <span className="text-secondary">Always allow</span>
            </span>
            <span className="flex items-center gap-1">
                <LemonBadge.Number count={counts.needs_approval} status="warning" showZero />
                <span className="text-secondary">Needs approval</span>
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
