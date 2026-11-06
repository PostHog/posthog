import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSnack, LemonTag, ProfilePicture, Spinner, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ServerIcon } from '../scene/icons'
import { GatewayAddServerModal } from './GatewayAddServerModal'
import { GatewayConnectionModal } from './GatewayConnectionModal'
import { GatewayServersSearch } from './GatewayServersSearch'
import { toProfileUser } from './gatewayUtils'
import { GATEWAY_CATEGORY_LABELS, GatewayServerEntry, isTemplateOnlyServer, mcpGatewayLogic } from './mcpGatewayLogic'

export function GatewayServersLoadError({
    onRetry,
    serverDetail = false,
}: {
    onRetry: () => void
    serverDetail?: boolean
}): JSX.Element {
    return (
        <LemonBanner type="error" action={{ children: 'Try again', onClick: onRetry }}>
            {serverDetail ? "Couldn't load this MCP server. Try again." : "Couldn't load MCP servers. Try again."}
        </LemonBanner>
    )
}

export function GatewayServersHome({ onOpenServer }: { onOpenServer?: (serverId: string) => void } = {}): JSX.Element {
    const {
        canAddServers,
        filteredServers,
        servers,
        serversLoadFailed,
        serversLoading,
        templatesLoading,
        searchQuery,
        categoryFilter,
        categoryCounts,
        isAdmin,
        mergedServers,
    } = useValues(mcpGatewayLogic)
    const { loadServers, openAddServerModal, setSearchQuery, setCategoryFilter } = useActions(mcpGatewayLogic)

    const categories = Object.keys(GATEWAY_CATEGORY_LABELS).filter((category) => categoryCounts[category])

    return (
        <div className="flex flex-col gap-4">
            <GatewayAddServerModal />
            <GatewayConnectionModal />

            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                    <h2 className="mb-1">MCP servers</h2>
                    <p className="mb-0 text-secondary">
                        Connect tools for yourself, your teammates, and PostHog agents.
                    </p>
                </div>
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={openAddServerModal}
                    disabledReason={canAddServers ? undefined : 'Only project admins can add MCP servers.'}
                >
                    Add server
                </LemonButton>
            </div>

            <div className="flex items-center justify-between gap-2 text-sm text-secondary">
                <span>
                    {filteredServers.length} {filteredServers.length === 1 ? 'server' : 'servers'}
                </span>
                {(searchQuery || categoryFilter) && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() => {
                            setSearchQuery('')
                            setCategoryFilter(null)
                        }}
                    >
                        Clear filters
                    </LemonButton>
                )}
            </div>

            <GatewayServersSearch />

            <div className="flex items-center gap-2 flex-wrap">
                <LemonButton
                    size="small"
                    type={categoryFilter === null ? 'primary' : 'tertiary'}
                    aria-pressed={categoryFilter === null}
                    onClick={() => setCategoryFilter(null)}
                >
                    All <LemonSnack className="ml-1">{mergedServers.length}</LemonSnack>
                </LemonButton>
                {categories.map((category) => (
                    <LemonButton
                        key={category}
                        size="small"
                        type={categoryFilter === category ? 'primary' : 'tertiary'}
                        aria-pressed={categoryFilter === category}
                        onClick={() => setCategoryFilter(category)}
                    >
                        {GATEWAY_CATEGORY_LABELS[category]}{' '}
                        <LemonSnack className="ml-1">{categoryCounts[category]}</LemonSnack>
                    </LemonButton>
                ))}
            </div>

            {serversLoadFailed && servers.length > 0 && <GatewayServersLoadError onRetry={loadServers} />}

            {serversLoadFailed && servers.length === 0 ? (
                <GatewayServersLoadError onRetry={loadServers} />
            ) : (serversLoading || templatesLoading) && filteredServers.length === 0 ? (
                <div className="flex items-center justify-center gap-2 p-8 text-secondary">
                    <Spinner /> Loading MCP servers
                </div>
            ) : filteredServers.length === 0 ? (
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
                        <GatewayServerCard key={server.id} server={server} onOpenServer={onOpenServer} />
                    ))}
                </div>
            )}
        </div>
    )
}

export function GatewayServerCard({
    server,
    onOpenServer,
}: {
    server: GatewayServerEntry
    onOpenServer?: (serverId: string) => void
}): JSX.Element {
    const { isAdmin, connectingServerId } = useValues(mcpGatewayLogic)
    const { connectServer, reconnectServer } = useActions(mcpGatewayLogic)

    // Catalog templates without a registry row: connect-only, no detail scene.
    const recommended = isTemplateOnlyServer(server)
    const connection = server.your_connection
    const connected = Boolean(connection?.is_enabled && !connection.pending_oauth && !connection.needs_reauth)
    const needsReconnect = Boolean(connection?.pending_oauth || connection?.needs_reauth)
    const canReconnect = Boolean(connection && (server.auth_type === 'oauth' || needsReconnect))
    const connecting = connectingServerId === server.id
    const disabled = !server.is_team_enabled
    const canConnectIndividual = !connection
    const connectionDisabledReason = server.is_revoked_for_you
        ? 'Ask an admin to restore your access to this server.'
        : recommended && disabled
          ? 'Catalog servers are turned off for this team. An admin can enable them in Team settings.'
          : disabled
            ? 'This server is turned off for the team.'
            : undefined
    const openServer = (): void => {
        if (onOpenServer) {
            onOpenServer(server.id)
        } else {
            router.actions.push(urls.mcpGatewayServer(server.id))
        }
    }

    return (
        <div
            className={`border rounded p-3 flex items-center gap-3 bg-surface-primary hover:border-accent transition-colors ${
                disabled ? 'opacity-60' : ''
            } ${recommended ? '' : 'cursor-pointer'}`}
            role={recommended ? undefined : 'button'}
            tabIndex={recommended ? undefined : 0}
            onClick={recommended ? undefined : openServer}
            onKeyDown={(event) => {
                if (
                    !recommended &&
                    event.target === event.currentTarget &&
                    (event.key === 'Enter' || event.key === ' ')
                ) {
                    event.preventDefault()
                    openServer()
                }
            }}
        >
            <div className="shrink-0">
                <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={42} />
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">{server.name}</span>
                    {connected && <LemonTag type="success">Connected</LemonTag>}
                    {connection?.pending_oauth && <LemonTag type="warning">Finishing setup</LemonTag>}
                    {connection?.needs_reauth && <LemonTag type="danger">Needs reauth</LemonTag>}
                    {connection && !connection.is_enabled && <LemonTag type="muted">Off for you</LemonTag>}
                    {server.is_revoked_for_you && <LemonTag type="danger">Access revoked</LemonTag>}
                    {disabled && (
                        <Tooltip
                            title={
                                recommended
                                    ? 'Catalog servers are turned off for this team. An admin can enable them in Team settings.'
                                    : undefined
                            }
                        >
                            <LemonTag type="muted">Off</LemonTag>
                        </Tooltip>
                    )}
                </div>
                <div className="text-sm text-secondary truncate">{server.description || server.url}</div>
                {isAdmin && !recommended && <PeopleRow server={server} />}
            </div>
            <div className="shrink-0">
                {canReconnect && connection ? (
                    <LemonButton
                        size="small"
                        type="primary"
                        disabledReason={connectionDisabledReason}
                        onClick={() => reconnectServer(connection.installation_id)}
                        stopPropagation
                        data-attr="mcp-server-reconnect"
                    >
                        Reconnect
                    </LemonButton>
                ) : canConnectIndividual ? (
                    connecting ? (
                        <LemonButton size="small" disabledReason="Authorizing…" icon={<Spinner />} stopPropagation>
                            Authorizing…
                        </LemonButton>
                    ) : (
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => connectServer(server.id)}
                            disabledReason={connectionDisabledReason}
                            stopPropagation
                        >
                            Connect
                        </LemonButton>
                    )
                ) : (
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconGear />}
                        onClick={openServer}
                        aria-label={`Configure ${server.name}`}
                        stopPropagation
                    >
                        Configure
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

function PeopleRow({ server }: { server: GatewayServerEntry }): JSX.Element {
    if (!server.is_team_enabled) {
        return <div className="text-xs text-secondary mt-1">Disabled. Enable it in Team settings.</div>
    }
    const connections = server.connections ?? []
    // `agents` holds one row per member grant, so an agent repeats once per member sharing it.
    const agentCount = new Set((server.agents ?? []).map((agent) => agent.service_account_id)).size
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
