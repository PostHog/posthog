import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear } from '@posthog/icons'
import { Badge, Button, Card, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { ServerIcon } from '../scene/icons'
import { GatewayServerEntry, isTemplateOnlyServer, mcpGatewayLogic } from './mcpGatewayLogic'
import { QuillGatewayServerPeopleRow } from './QuillGatewayServerPeopleRow'

const CATALOG_OFF_REASON = 'Catalog servers are turned off for this team. An admin can enable them in Team settings.'

export function QuillGatewayServerCard({
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
          ? CATALOG_OFF_REASON
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

    const summary = (
        <>
            <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={42} />
            <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2">
                    <Text size="sm" weight="semibold" render={<span className="m-0" />}>
                        {server.name}
                    </Text>
                    {connected && <Badge variant="success">Connected</Badge>}
                    {connection?.pending_oauth && <Badge variant="warning">Finishing setup</Badge>}
                    {connection?.needs_reauth && <Badge variant="destructive">Needs reauth</Badge>}
                    {connection && !connection.is_enabled && <Badge>Off for you</Badge>}
                    {server.is_revoked_for_you && <Badge variant="destructive">Access revoked</Badge>}
                    {disabled &&
                        (recommended ? (
                            <Tooltip>
                                <TooltipTrigger render={<Badge tabIndex={0} />}>Off</TooltipTrigger>
                                <TooltipContent>{CATALOG_OFF_REASON}</TooltipContent>
                            </Tooltip>
                        ) : (
                            <Badge>Off</Badge>
                        ))}
                </span>
                <Text size="xs" variant="muted" render={<span className="m-0 truncate" />}>
                    {server.description || server.url}
                </Text>
                {isAdmin && !recommended && <QuillGatewayServerPeopleRow server={server} />}
            </span>
        </>
    )

    return (
        <Card size="sm" className={cn('p-0', disabled && 'opacity-60')}>
            <div className="flex flex-wrap items-center gap-2 pr-3">
                {recommended ? (
                    <div className="flex min-w-48 flex-1 items-center gap-3 px-3 py-2">{summary}</div>
                ) : (
                    <button
                        type="button"
                        className="flex min-w-48 flex-1 items-center gap-3 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={openServer}
                    >
                        {summary}
                    </button>
                )}
                {canReconnect && connection ? (
                    <Button
                        variant="primary"
                        disabledReason={connectionDisabledReason}
                        onClick={() => reconnectServer(connection.installation_id)}
                        data-attr="mcp-server-reconnect"
                    >
                        Reconnect
                    </Button>
                ) : canConnectIndividual ? (
                    connecting ? (
                        <Button variant="outline" loading>
                            Authorizing…
                        </Button>
                    ) : (
                        <Button
                            variant="outline"
                            onClick={() => connectServer(server.id)}
                            disabledReason={connectionDisabledReason}
                        >
                            Connect
                        </Button>
                    )
                ) : (
                    <Button variant="outline" onClick={openServer} aria-label={`Configure ${server.name}`}>
                        <IconGear />
                        Configure
                    </Button>
                )}
            </div>
        </Card>
    )
}
