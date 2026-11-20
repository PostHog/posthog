import { useActions, useValues } from 'kea'

import { IconCheck, IconPlus, IconSparkles, IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    Field,
    FieldContent,
    FieldDescription,
    FieldLabel,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Switch,
    Text,
    cn,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { fullName } from 'lib/utils/strings'

import { gatewayServerLogic } from './gatewayServerLogic'
import { agentServerAccessKey, mcpGatewayLogic, memberServerAccessKey } from './mcpGatewayLogic'
import { QuillAgentGrantScopeControl } from './QuillAgentGrantScopeControl'
import { QuillGatewayAgentAccessModal } from './QuillGatewayAgentAccessModal'
import { QuillGatewayConnectionStatus } from './QuillGatewayConnectionStatus'
import { QuillRemoveAllSharesButton } from './QuillRemoveAllSharesButton'

export function QuillGatewayAccessSection(): JSX.Element | null {
    const { agentShareDisabledReason, server } = useValues(gatewayServerLogic)
    const { openAgentAccessModal } = useActions(gatewayServerLogic)
    const {
        agentServerAccessLoadingKeys,
        allServersEnabledLoading,
        canManageAgentAccess,
        currentUserId,
        isAdmin,
        memberServerAccessLoadingKeys,
        serverEnabledLoadingIds,
    } = useValues(mcpGatewayLogic)
    const { setAgentServerAccess, setMemberServerAccess, toggleServerEnabled } = useActions(mcpGatewayLogic)

    if (!server || (!isAdmin && !canManageAgentAccess)) {
        return null
    }

    const connections = server.connections ?? []
    const yourInstallationId = server.your_connection?.installation_id

    return (
        <div className="flex flex-col gap-3">
            <QuillGatewayAgentAccessModal />
            <Heading size="sm" render={<h3 className="m-0" />}>
                Access
            </Heading>

            {isAdmin && (
                <>
                    <Field orientation="horizontal" className="rounded-md border border-border bg-muted p-3">
                        <FieldContent>
                            <FieldLabel htmlFor="mcp-gateway-server-team-enabled">
                                Enabled for your organization
                            </FieldLabel>
                            <FieldDescription>
                                {server.is_team_enabled
                                    ? `Anyone in your organization can find and use ${server.name}. Each person connects with their own account.`
                                    : `${server.name} is turned off for everyone in your organization.`}
                            </FieldDescription>
                        </FieldContent>
                        <Switch
                            id="mcp-gateway-server-team-enabled"
                            checked={server.is_team_enabled}
                            disabledReason={
                                allServersEnabledLoading || serverEnabledLoadingIds.has(server.id)
                                    ? 'Saving your change'
                                    : undefined
                            }
                            aria-label={`${server.is_team_enabled ? 'Turn off' : 'Turn on'} ${server.name} for your organization`}
                            onCheckedChange={(checked: boolean) => toggleServerEnabled(server.id, checked)}
                        />
                    </Field>

                    <div className="flex items-center gap-2">
                        <Text size="xs" weight="semibold" variant="muted" render={<span className="m-0 uppercase" />}>
                            People connected
                        </Text>
                        <Badge>{connections.length}</Badge>
                    </div>
                    {connections.length === 0 ? (
                        <div className="rounded-md border border-dashed border-border p-3">
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                No one has connected yet.
                            </Text>
                        </div>
                    ) : (
                        <div className="divide-y divide-border rounded-md border border-border">
                            {connections.map((connection) => {
                                const isYou = connection.installation_id === yourInstallationId
                                const accessRevoked = server.revoked_user_ids.includes(connection.user.id)
                                const loading = memberServerAccessLoadingKeys.has(
                                    memberServerAccessKey(connection.user.id, server.id)
                                )

                                return (
                                    <Item
                                        key={connection.installation_id}
                                        size="sm"
                                        className={cn('flex-wrap', accessRevoked && 'opacity-60')}
                                    >
                                        <ItemMedia>
                                            <QuillPersonAvatar
                                                name={fullName(connection.user)}
                                                email={connection.user.email}
                                            />
                                        </ItemMedia>
                                        <ItemContent className="min-w-0">
                                            <ItemTitle>
                                                <span className="truncate">
                                                    {connection.user.first_name || connection.user.email}
                                                </span>
                                                {isYou && <Badge variant="info">You</Badge>}
                                            </ItemTitle>
                                            <ItemDescription className="truncate">
                                                {connection.user.email}
                                            </ItemDescription>
                                        </ItemContent>
                                        <ItemActions className="flex-wrap">
                                            {!isYou && (
                                                <Button
                                                    variant={accessRevoked ? 'default' : 'destructive-outline'}
                                                    loading={loading}
                                                    onClick={() =>
                                                        setMemberServerAccess(
                                                            connection.user.id,
                                                            server.id,
                                                            accessRevoked
                                                        )
                                                    }
                                                >
                                                    {accessRevoked ? <IconCheck /> : <IconX />}
                                                    {accessRevoked ? 'Restore' : 'Revoke'}
                                                </Button>
                                            )}
                                            <QuillGatewayConnectionStatus
                                                pendingOauth={connection.pending_oauth}
                                                needsReauth={connection.needs_reauth}
                                                accessRevoked={accessRevoked}
                                                lastUsedAt={connection.last_used_at}
                                            />
                                        </ItemActions>
                                    </Item>
                                )
                            })}
                        </div>
                    )}
                </>
            )}

            <div className="flex flex-wrap items-center gap-2">
                <Text size="xs" weight="semibold" variant="muted" render={<span className="m-0 uppercase" />}>
                    Agents
                </Text>
                <Badge>{server.agents.length}</Badge>
                <Button
                    className="ms-auto"
                    onClick={() => openAgentAccessModal()}
                    disabledReason={agentShareDisabledReason}
                >
                    <IconPlus />
                    Share access with an agent
                </Button>
            </div>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Agents only use your {server.name} connection if you share it. With "Only me", an agent uses it on runs
                you start. With "Everyone in this project", any agent run in this project can use it, including scouts,
                automatic support replies, and your teammates' runs.
            </Text>

            {server.agents.length === 0 ? (
                <div className="rounded-md border border-dashed border-border p-3">
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        No agents have access. Share your connection and choose which tools the agent may call.
                    </Text>
                </div>
            ) : (
                <div className="divide-y divide-border rounded-md border border-border">
                    {server.agents.map((agent) => {
                        const sharedByYou = agent.user.id === currentUserId
                        const agentShareCount = server.agents.filter(
                            (candidate) => candidate.service_account_id === agent.service_account_id
                        ).length

                        return (
                            <Item key={`${agent.service_account_id}:${agent.user.id}`} size="sm" className="flex-wrap">
                                <ItemMedia variant="icon">
                                    <IconSparkles />
                                </ItemMedia>
                                <ItemContent className="min-w-0">
                                    <ItemTitle>
                                        <span className="truncate">{agent.name}</span>
                                    </ItemTitle>
                                    <ItemDescription className="truncate">
                                        <span className="font-mono">{agent.handle}</span>
                                        <span>
                                            {sharedByYou
                                                ? ' · shared by you'
                                                : ` · shared ${agent.scope === 'team' ? 'to the team ' : ''}by ${agent.user.first_name || agent.user.email}`}
                                        </span>
                                    </ItemDescription>
                                </ItemContent>
                                <ItemActions className="flex-wrap">
                                    {sharedByYou && (
                                        <QuillAgentGrantScopeControl
                                            accountId={agent.service_account_id}
                                            serverId={server.id}
                                            scope={agent.scope}
                                        />
                                    )}
                                    {sharedByYou ? (
                                        <Button
                                            variant="destructive-outline"
                                            loading={agentServerAccessLoadingKeys.has(
                                                agentServerAccessKey(agent.service_account_id, server.id)
                                            )}
                                            onClick={() =>
                                                setAgentServerAccess(agent.service_account_id, server.id, false)
                                            }
                                        >
                                            <IconX />
                                            Revoke
                                        </Button>
                                    ) : (
                                        <QuillRemoveAllSharesButton
                                            accountId={agent.service_account_id}
                                            accountName={agent.name}
                                            serverId={server.id}
                                            serverName={server.name}
                                            shareCount={agentShareCount}
                                        />
                                    )}
                                </ItemActions>
                            </Item>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
