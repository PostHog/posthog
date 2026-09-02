import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSnack,
    LemonTag,
    ProfilePicture,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { InstallCustomAuthTypeEnumApi } from '../generated/api.schemas'
import { ServerIcon } from '../scene/icons'
import { GatewayAddServerModal } from './GatewayAddServerModal'
import { GatewayServersSearch } from './GatewayServersSearch'
import { toProfileUser } from './gatewayUtils'
import { GATEWAY_CATEGORY_LABELS, GatewayServerEntry, isTemplateOnlyServer, mcpGatewayLogic } from './mcpGatewayLogic'

const AUTH_TYPE_OPTIONS = [
    { value: 'oauth' as const, label: 'OAuth' },
    { value: 'api_key' as const, label: 'API key' },
]

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
                {needsReconnect && connection ? (
                    <LemonButton
                        size="small"
                        type="primary"
                        disabledReason={connectionDisabledReason}
                        onClick={() => reconnectServer(connection.installation_id)}
                        stopPropagation
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

function GatewayConnectionModal(): JSX.Element | null {
    const {
        connectionModalServer,
        connectionAuthType,
        connectionApiKey,
        connectionClientId,
        connectionClientSecret,
        connectingServerId,
        connectionSubmitDisabledReason,
    } = useValues(mcpGatewayLogic)
    const {
        closeConnectionModal,
        setConnectionAuthType,
        setConnectionApiKey,
        setConnectionClientId,
        setConnectionClientSecret,
        submitConnection,
    } = useActions(mcpGatewayLogic)

    if (!connectionModalServer) {
        return null
    }

    const isCustomServer = !connectionModalServer.template_id
    const connecting = connectingServerId === connectionModalServer.id
    const closeModal = (): void => {
        if (!connecting) {
            closeConnectionModal()
        }
    }

    return (
        <LemonModal
            isOpen
            onClose={closeModal}
            title={`Connect ${connectionModalServer.name}`}
            description={
                isCustomServer
                    ? 'Choose how this server authenticates, then enter your personal credentials.'
                    : 'Enter the credentials for your personal connection.'
            }
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={connecting ? 'Connection in progress' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        form="mcp-gateway-connect-server-form"
                        loading={connecting}
                        disabledReason={connectionSubmitDisabledReason ?? undefined}
                    >
                        Connect
                    </LemonButton>
                </div>
            }
            width={560}
        >
            <form
                id="mcp-gateway-connect-server-form"
                className="flex flex-col gap-3"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (!connecting && !connectionSubmitDisabledReason) {
                        submitConnection()
                    }
                }}
            >
                {isCustomServer && (
                    <LemonField.Pure label="Authentication" htmlFor="mcp-gateway-connection-authentication">
                        <LemonSelect<InstallCustomAuthTypeEnumApi>
                            id="mcp-gateway-connection-authentication"
                            value={connectionAuthType}
                            onChange={setConnectionAuthType}
                            options={AUTH_TYPE_OPTIONS}
                            fullWidth
                        />
                    </LemonField.Pure>
                )}

                {connectionAuthType === 'api_key' ? (
                    <LemonField.Pure
                        label={isCustomServer ? 'API key (optional)' : 'API key'}
                        help={
                            isCustomServer
                                ? 'Leave this blank if the server does not require authentication.'
                                : undefined
                        }
                        htmlFor="mcp-gateway-connection-api-key"
                    >
                        <LemonInput
                            id="mcp-gateway-connection-api-key"
                            type="password"
                            value={connectionApiKey}
                            onChange={setConnectionApiKey}
                            placeholder="Enter API key"
                            autoFocus
                            fullWidth
                        />
                    </LemonField.Pure>
                ) : (
                    isCustomServer && (
                        <LemonCollapse
                            panels={[
                                {
                                    key: 'oauth-settings',
                                    header: 'Advanced OAuth settings',
                                    content: (
                                        <div className="flex flex-col gap-3">
                                            <LemonField.Pure
                                                label="OAuth client ID"
                                                help="Leave blank to let PostHog register a client for you."
                                                htmlFor="mcp-gateway-connection-client-id"
                                            >
                                                <LemonInput
                                                    id="mcp-gateway-connection-client-id"
                                                    value={connectionClientId}
                                                    onChange={setConnectionClientId}
                                                    placeholder="Optional"
                                                    fullWidth
                                                />
                                            </LemonField.Pure>
                                            <LemonField.Pure
                                                label="OAuth client secret"
                                                help="Only needed for confidential clients."
                                                htmlFor="mcp-gateway-connection-client-secret"
                                            >
                                                <LemonInput
                                                    id="mcp-gateway-connection-client-secret"
                                                    type="password"
                                                    value={connectionClientSecret}
                                                    onChange={setConnectionClientSecret}
                                                    placeholder="Optional"
                                                    fullWidth
                                                />
                                            </LemonField.Pure>
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    )
                )}
            </form>
        </LemonModal>
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
