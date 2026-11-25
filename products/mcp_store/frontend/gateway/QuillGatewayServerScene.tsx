import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft, IconExternal, IconTrash, IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Separator,
    Skeleton,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ServerIcon } from '../scene/icons'
import { gatewayServerLogic } from './gatewayServerLogic'
import { getGatewayServerRemovalAction } from './gatewayServerRemoval'
import { AUTH_TYPE_LABELS, confirmGatewayServerRemoval } from './GatewayServerScene'
import { mcpGatewayLogic } from './mcpGatewayLogic'
import { QuillGatewayAccessSection } from './QuillGatewayAccessSection'
import { QuillGatewayConnectionModal } from './QuillGatewayConnectionModal'
import { QuillGatewayServersLoadError } from './QuillGatewayServersLoadError'
import { QuillToolPoliciesSection } from './QuillToolPoliciesSection'

export function QuillGatewayServerScene({ onBack }: { id: string; onBack?: () => void }): JSX.Element {
    const { server, serverLoading, serversLoadFailed, isAdmin, canManageAgentAccess } = useValues(gatewayServerLogic)
    const { user } = useValues(userLogic)
    const { connectingServerId, disconnectingInstallationIds, removingServerIds, updatingInstallationIds } =
        useValues(mcpGatewayLogic)
    const { connectServer, disconnectServer, loadServers, reconnectServer, removeServer, toggleYourConnectionEnabled } =
        useActions(mcpGatewayLogic)
    const goBack = onBack ?? (() => router.actions.push(urls.mcpGateway()))

    const backButton = (
        <Button variant="default" className="self-start" onClick={goBack}>
            <IconArrowLeft />
            Back to servers
        </Button>
    )

    if (!server && serverLoading) {
        return (
            <div className="flex flex-col gap-4">
                <Skeleton className="h-14" />
                <Skeleton className="h-32" />
            </div>
        )
    }

    if (!server && serversLoadFailed) {
        return (
            <div className="flex flex-col gap-4">
                {backButton}
                <QuillGatewayServersLoadError serverDetail onRetry={loadServers} />
            </div>
        )
    }

    if (!server) {
        return (
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Server not found.
            </Text>
        )
    }

    const connection = server.your_connection
    const removalAction = getGatewayServerRemovalAction(server, isAdmin, user?.id)
    const removalPending =
        removingServerIds.has(server.id) ||
        Boolean(connection && disconnectingInstallationIds.has(connection.installation_id))
    const needsReconnect = Boolean(connection?.pending_oauth || connection?.needs_reauth)
    const canReconnect = Boolean(connection && (server.auth_type === 'oauth' || needsReconnect))
    const reconnectDisabledReason = !server.is_team_enabled
        ? 'This server is turned off for the team.'
        : server.is_revoked_for_you
          ? 'Ask an admin to restore your access first.'
          : undefined
    const confirmRemoval = (): void =>
        confirmGatewayServerRemoval({ server, removalAction, removeServer, disconnectServer })

    return (
        <div className="flex flex-col gap-4">
            <QuillGatewayConnectionModal />

            {backButton}

            {serversLoadFailed && <QuillGatewayServersLoadError serverDetail onRetry={loadServers} />}

            {connection && needsReconnect && (
                <Item tone="destructive" size="sm">
                    <ItemContent>
                        <ItemTitle>Reconnect required</ItemTitle>
                        <ItemDescription>
                            {server.name} tools are not available to you or your agents until you reconnect.
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button
                            variant="primary"
                            disabledReason={reconnectDisabledReason}
                            onClick={() => reconnectServer(connection.installation_id)}
                            data-attr="mcp-server-reconnect"
                        >
                            Reconnect your account
                        </Button>
                    </ItemActions>
                </Item>
            )}

            <div className="flex flex-wrap items-start gap-3">
                <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={56} />
                <div className="flex min-w-48 flex-1 flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <Heading size="base" render={<h2 className="m-0 truncate" />}>
                            {server.name}
                        </Heading>
                        {isAdmin && !server.is_team_enabled && <Badge>Off</Badge>}
                    </div>
                    {server.description && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {server.description}
                        </Text>
                    )}
                    <div className="flex flex-wrap items-center gap-3">
                        <Text size="xs" variant="muted" render={<span className="m-0 min-w-0 truncate" />}>
                            {[
                                server.created_by &&
                                    `Added by ${server.created_by.first_name || server.created_by.email}`,
                                server.template_auth_type && AUTH_TYPE_LABELS[server.template_auth_type],
                                server.url,
                            ]
                                .filter(Boolean)
                                .join(' · ')}
                        </Text>
                        {server.docs_url && (
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to={server.docs_url} target="_blank" />}
                            >
                                <IconExternal />
                                Docs
                            </Button>
                        )}
                    </div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                    {connection ? (
                        <>
                            <div className="flex flex-wrap items-center gap-2">
                                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                    Available to you
                                </Text>
                                <ToggleGroup
                                    size="sm"
                                    aria-label="Available to you"
                                    value={[connection.is_enabled ? 'on' : 'off']}
                                    onValueChange={(next: string[]) => {
                                        if (next[0]) {
                                            toggleYourConnectionEnabled(connection.installation_id, next[0] === 'on')
                                        }
                                    }}
                                >
                                    {[
                                        { value: 'on', label: 'On' },
                                        { value: 'off', label: 'Off' },
                                    ].map((option) => (
                                        <ToggleGroupItem
                                            key={option.value}
                                            value={option.value}
                                            disabledReason={
                                                updatingInstallationIds.has(connection.installation_id)
                                                    ? 'Updating your connection'
                                                    : undefined
                                            }
                                        >
                                            {option.label}
                                        </ToggleGroupItem>
                                    ))}
                                </ToggleGroup>
                            </div>
                            {canReconnect && !needsReconnect && (
                                <Button
                                    variant="primary"
                                    disabledReason={reconnectDisabledReason}
                                    onClick={() => reconnectServer(connection.installation_id)}
                                    data-attr="mcp-server-reconnect"
                                >
                                    Reconnect your account
                                </Button>
                            )}
                            {removalAction && (
                                <Button
                                    variant={removalAction === 'disconnect' ? 'default' : 'destructive-outline'}
                                    loading={removalPending}
                                    onClick={confirmRemoval}
                                >
                                    {removalAction === 'disconnect' ? <IconX /> : <IconTrash />}
                                    {removalAction === 'disconnect' ? 'Disconnect' : 'Delete'}
                                </Button>
                            )}
                        </>
                    ) : (
                        <Button
                            variant="primary"
                            loading={connectingServerId === server.id}
                            disabledReason={
                                server.is_team_enabled ? undefined : 'This server is turned off for the team.'
                            }
                            onClick={() => connectServer(server.id)}
                        >
                            Connect your account
                        </Button>
                    )}
                    {!connection && removalAction === 'delete_for_everyone' && (
                        <Button variant="destructive-outline" loading={removalPending} onClick={confirmRemoval}>
                            <IconTrash />
                            Delete server
                        </Button>
                    )}
                </div>
            </div>

            {server.is_revoked_for_you && (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            A project admin disabled your access to this server. Ask an admin to restore it.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            {connection && !connection.is_enabled && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            This server is off for you. Turn it on to offer its tools to PostHog and your agents.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            <Separator />

            {(isAdmin || canManageAgentAccess) && <QuillGatewayAccessSection />}

            <QuillToolPoliciesSection />
        </div>
    )
}
