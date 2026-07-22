import { useActions, useValues } from 'kea'

import { LemonSwitch, LemonTag, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { gatewayServerLogic } from './gatewayServerLogic'
import { toProfileUser } from './gatewayUtils'
import { agentServerAccessKey, mcpGatewayLogic } from './mcpGatewayLogic'

/** Admin-only "Access" section on the server detail: team availability, shared
 * credential, personal-connection allowance, connected people and agents. */
export function GatewayAccessSection(): JSX.Element | null {
    const { server } = useValues(gatewayServerLogic)
    const {
        agentServerAccessLoadingKeys,
        allServersEnabledLoading,
        personalConnectionsLoadingIds,
        serverEnabledLoadingIds,
        serviceAccounts,
        serviceAccountsLoading,
    } = useValues(mcpGatewayLogic)
    const { toggleServerEnabled, toggleAllowPersonal, setAgentServerAccess } = useActions(mcpGatewayLogic)

    if (!server) {
        return null
    }

    const connections = server.connections ?? []

    return (
        <div className="flex flex-col gap-3">
            <h3 className="mb-0">Access</h3>

            <div className="border rounded p-3 flex items-center justify-between gap-3">
                <div>
                    <div className="font-semibold">Available to team members</div>
                    <div className="text-sm text-secondary">
                        {server.is_team_enabled
                            ? server.auth_mode === 'shared'
                                ? `Members use ${server.name} through the shared credential — nothing for them to set up.`
                                : `Members can connect their own ${server.name} account.`
                            : `Turned off — members can't see or call ${server.name}.`}
                    </div>
                </div>
                <LemonSwitch
                    checked={server.is_team_enabled}
                    loading={allServersEnabledLoading || serverEnabledLoadingIds.has(server.id)}
                    aria-label={`${server.is_team_enabled ? 'Turn off' : 'Turn on'} ${server.name} for team members`}
                    onChange={(checked) => toggleServerEnabled(server.id, checked)}
                />
            </div>

            {server.auth_mode === 'shared' && (
                <>
                    <div className="border rounded p-3 flex items-center justify-between gap-3">
                        <div>
                            <div className="font-mono text-sm">
                                {server.shared_credential?.managed_by?.email ?? 'shared credential'}
                            </div>
                            <div className="text-sm text-secondary">
                                Shared credential — managed by{' '}
                                {server.shared_credential?.managed_by?.first_name ?? 'an admin'}. Everyone on the team
                                calls {server.name} through this account.
                            </div>
                        </div>
                    </div>
                    <div className="border rounded p-3 flex items-center justify-between gap-3">
                        <div>
                            <div className="font-semibold">Personal connections</div>
                            <div className="text-sm text-secondary">
                                Let members authenticate their own {server.name} account on top of the shared
                                credential.
                            </div>
                        </div>
                        <LemonSwitch
                            checked={server.allow_personal_connections}
                            loading={personalConnectionsLoadingIds.has(server.id)}
                            aria-label={`${server.allow_personal_connections ? 'Disable' : 'Enable'} personal ${server.name} connections`}
                            onChange={(checked) => toggleAllowPersonal(server.id, checked)}
                        />
                    </div>
                </>
            )}

            <div>
                <div className="text-xs uppercase text-secondary font-semibold mb-1">
                    People connected · {connections.length}
                </div>
                {connections.length === 0 ? (
                    <div className="border border-dashed rounded p-3 text-sm text-secondary">
                        {server.auth_mode === 'shared'
                            ? 'No one has connected a personal account — everyone uses the shared credential.'
                            : 'No one has connected yet.'}
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

            <div>
                <div className="text-xs uppercase text-secondary font-semibold mb-1">
                    Agents · {serviceAccounts.length}
                </div>
                <div className="text-sm text-secondary mb-2">
                    Agent access is separate from team member availability.
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
                            const shared = account.server_ids.includes(server.id)
                            return (
                                <div key={account.id} className="flex items-center gap-2 p-2">
                                    <div className="flex-1 min-w-0">
                                        <div className="font-semibold">{account.name}</div>
                                        <div className="text-xs text-secondary truncate">{account.description}</div>
                                    </div>
                                    <LemonTag type={account.product_enabled ? 'success' : 'muted'} size="small">
                                        {account.product_enabled ? 'Product available' : 'Product unavailable'}
                                    </LemonTag>
                                    <LemonTag type={account.status === 'paused' ? 'warning' : 'success'} size="small">
                                        {account.status === 'paused' ? 'MCP paused' : 'MCP enabled'}
                                    </LemonTag>
                                    <LemonSwitch
                                        checked={shared}
                                        loading={agentServerAccessLoadingKeys.has(
                                            agentServerAccessKey(account.id, server.id)
                                        )}
                                        aria-label={`${shared ? 'Revoke' : 'Grant'} ${account.name} access to ${server.name}`}
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
