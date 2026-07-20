import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSnack, LemonTag, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { MCPGatewayServerApi } from '../generated/api.schemas'
import { ServerIcon } from '../scene/icons'
import { toProfileUser } from './gatewayUtils'
import { GATEWAY_CATEGORY_LABELS, mcpGatewayLogic } from './mcpGatewayLogic'

export function GatewayServersHome(): JSX.Element {
    const { filteredServers, serversLoading, searchQuery, categoryFilter, categoryCounts, isAdmin, servers } =
        useValues(mcpGatewayLogic)
    const { setSearchQuery, setCategoryFilter } = useActions(mcpGatewayLogic)

    const categories = Object.keys(GATEWAY_CATEGORY_LABELS).filter((category) => categoryCounts[category])

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2 flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Search team servers…"
                    value={searchQuery}
                    onChange={setSearchQuery}
                    className="max-w-md"
                />
            </div>

            <div className="flex items-center gap-2 flex-wrap">
                <LemonButton
                    size="small"
                    type={categoryFilter === null ? 'primary' : 'tertiary'}
                    onClick={() => setCategoryFilter(null)}
                >
                    All <LemonSnack className="ml-1">{servers.length}</LemonSnack>
                </LemonButton>
                {categories.map((category) => (
                    <LemonButton
                        key={category}
                        size="small"
                        type={categoryFilter === category ? 'primary' : 'tertiary'}
                        onClick={() => setCategoryFilter(category)}
                    >
                        {GATEWAY_CATEGORY_LABELS[category]}{' '}
                        <LemonSnack className="ml-1">{categoryCounts[category]}</LemonSnack>
                    </LemonButton>
                ))}
            </div>

            {filteredServers.length === 0 && !serversLoading ? (
                <div className="border border-dashed rounded p-8 text-center text-secondary">
                    <p className="font-semibold mb-1">No servers match.</p>
                    <p className="text-sm">
                        {isAdmin
                            ? 'Connect a server, or clear the search.'
                            : 'Try a different search, or ask an admin to add a server.'}
                    </p>
                </div>
            ) : (
                <div className="flex flex-col gap-2">
                    {filteredServers.map((server) => (
                        <GatewayServerCard key={server.id} server={server} />
                    ))}
                </div>
            )}
        </div>
    )
}

function GatewayServerCard({ server }: { server: MCPGatewayServerApi }): JSX.Element {
    const { isAdmin, connectingServerId } = useValues(mcpGatewayLogic)
    const { connectServer } = useActions(mcpGatewayLogic)

    const connected = Boolean(server.your_connection) || (server.auth_mode === 'shared' && !isAdmin)
    const connecting = connectingServerId === server.id
    const disabled = !server.is_team_enabled
    const canConnectIndividual = server.auth_mode === 'individual' && !connected

    return (
        <div
            className="border rounded p-3 flex items-center gap-3 hover:border-accent transition-colors"
            // Admins see disabled servers dimmed with an "Off" pill.
            style={disabled ? { opacity: 0.6 } : undefined}
        >
            <div className="shrink-0">
                <ServerIcon iconKey={server.icon_key || undefined} size={42} />
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <button
                        className="font-semibold text-left hover:text-accent"
                        onClick={() => router.actions.push(urls.mcpGatewayServer(server.id))}
                    >
                        {server.name}
                    </button>
                    {connected && <LemonTag type="success">Connected</LemonTag>}
                    {isAdmin && server.auth_mode === 'shared' && <LemonTag type="muted">🔑 Shared</LemonTag>}
                    {isAdmin && disabled && <LemonTag type="muted">Off</LemonTag>}
                </div>
                <div className="text-sm text-secondary truncate">{server.description || server.url}</div>
                {isAdmin && <PeopleRow server={server} />}
            </div>
            <div className="shrink-0">
                {canConnectIndividual ? (
                    connecting ? (
                        <LemonButton size="small" disabledReason="Authorizing…" icon={<Spinner />}>
                            Authorizing…
                        </LemonButton>
                    ) : (
                        <LemonButton size="small" type="secondary" onClick={() => connectServer(server.id)}>
                            Connect
                        </LemonButton>
                    )
                ) : (
                    <LemonButton
                        size="small"
                        icon={<IconGear />}
                        onClick={() => router.actions.push(urls.mcpGatewayServer(server.id))}
                    />
                )}
            </div>
        </div>
    )
}

function PeopleRow({ server }: { server: MCPGatewayServerApi }): JSX.Element {
    if (!server.is_team_enabled) {
        return <div className="text-xs text-secondary mt-1">Disabled — enable it in Team settings</div>
    }
    if (server.auth_mode === 'shared') {
        return (
            <div className="flex items-center gap-1 text-xs text-secondary mt-1">
                {server.shared_credential?.managed_by && (
                    <ProfilePicture user={toProfileUser(server.shared_credential.managed_by)} size="xs" />
                )}
                <span className="font-mono">{server.shared_credential?.managed_by?.email ?? 'shared credential'}</span>
                <span>· everyone on the team</span>
            </div>
        )
    }
    const connections = server.connections ?? []
    const agentCount = (server.agents ?? []).length
    return (
        <div className="flex items-center gap-2 text-xs text-secondary mt-1">
            <div className="flex -space-x-1">
                {connections.slice(0, 4).map((connection) => (
                    <ProfilePicture key={connection.installation_id} user={toProfileUser(connection.user)} size="xs" />
                ))}
            </div>
            <span>
                {connections.length === 0
                    ? 'No one connected yet'
                    : `${connections.length} teammate${connections.length === 1 ? '' : 's'} connected`}
                {agentCount > 0 && ` · ${agentCount} agent${agentCount === 1 ? '' : 's'}`}
            </span>
        </div>
    )
}
