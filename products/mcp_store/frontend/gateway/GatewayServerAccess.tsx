import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { gatewayServerLogic } from './gatewayServerLogic'
import { toProfileUser } from './gatewayUtils'
import { mcpGatewayLogic } from './mcpGatewayLogic'

/** Admin-only "Access" section on the server detail: team availability, shared
 * credential, personal-connection allowance, connected people and agents. */
export function GatewayAccessSection(): JSX.Element | null {
    const { server } = useValues(gatewayServerLogic)
    const { toggleServerEnabled, toggleAllowPersonal } = useActions(mcpGatewayLogic)

    if (!server) {
        return null
    }

    const connections = server.connections ?? []
    const agents = server.agents ?? []

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
                <div className="text-xs uppercase text-secondary font-semibold mb-1">Agents · {agents.length}</div>
                {agents.length === 0 ? (
                    <div className="border border-dashed rounded p-3 text-sm text-secondary">
                        No agents have access. Share this server with an agent from its service-account screen so it can
                        call {server.name} under its own tool policies.
                    </div>
                ) : (
                    <div className="border rounded divide-y">
                        {agents.map((agent) => (
                            <div key={agent.service_account_id} className="flex items-center gap-2 p-2">
                                <div className="font-semibold">{agent.name}</div>
                                <span className="font-mono text-xs text-secondary">{agent.handle}</span>
                                <div className="flex-1" />
                                {agent.status === 'paused' ? (
                                    <LemonTag type="warning">Paused</LemonTag>
                                ) : (
                                    <LemonTag type="success">Active</LemonTag>
                                )}
                            </div>
                        ))}
                    </div>
                )}
                <LemonButton
                    className="mt-2"
                    size="small"
                    type="secondary"
                    to={undefined}
                    disabledReason="Share access from the agent's detail page"
                >
                    + Share access with an agent
                </LemonButton>
            </div>
        </div>
    )
}
