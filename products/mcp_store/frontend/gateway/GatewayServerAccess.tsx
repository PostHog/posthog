import { useActions, useValues } from 'kea'

import { LemonSwitch, LemonTag, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { gatewayServerLogic } from './gatewayServerLogic'
import { sharedByLabel, toProfileUser } from './gatewayUtils'
import { agentServerAccessKey, mcpGatewayLogic } from './mcpGatewayLogic'

/** Access section on the server detail. Team and connection controls are
 * admin-only; agent grants follow the team's member-agent-access setting. */
export function GatewayAccessSection(): JSX.Element | null {
    const { server, agentSharesByAccountId } = useValues(gatewayServerLogic)
    const {
        agentServerAccessLoadingKeys,
        allServersEnabledLoading,
        canManageAgentAccess,
        isAdmin,
        serverEnabledLoadingIds,
        serviceAccounts,
        serviceAccountsLoading,
    } = useValues(mcpGatewayLogic)
    const { toggleServerEnabled, setAgentServerAccess } = useActions(mcpGatewayLogic)

    if (!server || !canManageAgentAccess) {
        return null
    }

    const connections = server.connections ?? []

    return (
        <div className="flex flex-col gap-3">
            <h3 className="mb-0">Access</h3>

            {isAdmin && (
                <>
                    <div className="border rounded p-3 flex items-center justify-between gap-3">
                        <div>
                            <div className="font-semibold">Available to the team</div>
                            <div className="text-sm text-secondary">
                                {server.is_team_enabled
                                    ? `Members can connect their own ${server.name} account.`
                                    : `Turned off. Members and agents can't see or call ${server.name}.`}
                            </div>
                        </div>
                        <LemonSwitch
                            checked={server.is_team_enabled}
                            loading={allServersEnabledLoading || serverEnabledLoadingIds.has(server.id)}
                            aria-label={`${server.is_team_enabled ? 'Turn off' : 'Turn on'} ${server.name} for the team`}
                            onChange={(checked) => toggleServerEnabled(server.id, checked)}
                        />
                    </div>

                    <div>
                        <div className="text-xs uppercase text-secondary font-semibold mb-1">
                            People connected · {connections.length}
                        </div>
                        {connections.length === 0 ? (
                            <div className="border border-dashed rounded p-3 text-sm text-secondary">
                                No one has connected yet.
                            </div>
                        ) : (
                            <div className="border rounded divide-y">
                                {connections.map((connection) => (
                                    <div key={connection.installation_id} className="flex items-center gap-2 p-2">
                                        <ProfilePicture user={toProfileUser(connection.user)} size="sm" showName />
                                        <div className="flex-1" />
                                        {connection.pending_oauth ? (
                                            <LemonTag type="warning">Pending</LemonTag>
                                        ) : connection.needs_reauth ? (
                                            <LemonTag type="danger">Needs reauth</LemonTag>
                                        ) : (
                                            <LemonTag type="success">Connected</LemonTag>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </>
            )}

            <div>
                <div className="text-xs uppercase text-secondary font-semibold mb-1">
                    Agents · {serviceAccounts.length}
                </div>
                <div className="text-sm text-secondary mb-2">
                    Sharing is personal. Only your agents use your {server.name} connection, and each teammate shares
                    their own.
                </div>
                {serviceAccountsLoading ? (
                    <div className="border border-dashed rounded p-3 text-sm text-secondary flex items-center gap-2">
                        <Spinner /> Loading agents…
                    </div>
                ) : serviceAccounts.length === 0 ? (
                    <div className="border border-dashed rounded p-3 text-sm text-secondary">
                        No PostHog agents are available for this project.
                    </div>
                ) : (
                    <div className="border rounded divide-y">
                        {serviceAccounts.map((account) => {
                            const share = agentSharesByAccountId[account.id]
                            const attribution = sharedByLabel(share?.sharedByOthers ?? [])
                            const sharedByYou = Boolean(share?.sharedByYou)
                            const needsConnection = !sharedByYou && server.your_connection === null
                            return (
                                <div key={account.id} className="flex items-center gap-2 p-2">
                                    <div className="flex-1 min-w-0">
                                        <div className="font-semibold">{account.name}</div>
                                        <div className="text-xs text-secondary truncate">{account.description}</div>
                                        {attribution && (
                                            <div className="text-xs text-secondary truncate">{attribution}</div>
                                        )}
                                    </div>
                                    <LemonTag type={account.status === 'paused' ? 'warning' : 'success'} size="small">
                                        {account.status === 'paused' ? 'MCP paused' : 'MCP enabled'}
                                    </LemonTag>
                                    <LemonSwitch
                                        checked={sharedByYou}
                                        loading={agentServerAccessLoadingKeys.has(
                                            agentServerAccessKey(account.id, server.id)
                                        )}
                                        disabledReason={
                                            needsConnection
                                                ? 'Connect this server before sharing it with an agent.'
                                                : undefined
                                        }
                                        tooltip={
                                            attribution
                                                ? `Turning this off also removes the shares your teammates made with ${account.name}.`
                                                : undefined
                                        }
                                        aria-label={`${sharedByYou ? 'Stop sharing' : 'Share'} your ${server.name} connection with ${account.name}`}
                                        onChange={(checked) => setAgentServerAccess(account.id, server.id, checked)}
                                    />
                                </div>
                            )
                        })}
                    </div>
                )}
            </div>
        </div>
    )
}
