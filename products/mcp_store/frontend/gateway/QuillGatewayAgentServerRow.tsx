import {
    Badge,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Switch,
    Text,
} from '@posthog/quill'

import type { ConnectionStateEnumApi, MCPGatewayServerApi } from '../generated/api.schemas'
import { ServerIcon } from '../scene/icons'
import { agentConnectionStatus, agentShareDisabledReason, canChangeAgentShare } from './GatewayAgentScene'
import { sharedByOthersLabel } from './gatewayUtils'
import { AgentServerShare } from './mcpGatewayLogic'
import { QuillAgentGrantScopeControl } from './QuillAgentGrantScopeControl'
import { QuillGatewayToolPoliciesButton } from './QuillGatewayToolPoliciesButton'
import { QuillRemoveAllSharesButton } from './QuillRemoveAllSharesButton'

export function QuillGatewayAgentServerRow({
    server,
    accountId,
    accountName,
    shared,
    share,
    connectionState,
    loading,
    onSetAccess,
    onOpenServer,
}: {
    server: MCPGatewayServerApi
    accountId: string
    accountName: string
    shared: boolean
    share?: AgentServerShare
    connectionState?: ConnectionStateEnumApi
    loading: boolean
    onSetAccess: (accountId: string, serverId: string, enabled: boolean) => void
    onOpenServer?: (serverId: string, scope: string) => void
}): JSX.Element {
    const sharedByYou = Boolean(share?.sharedByYou)
    const sharedByOthers = share?.sharedByOthers ?? []
    const attribution = share ? sharedByOthersLabel(share) : null
    const connectionDisabledReason = sharedByYou ? undefined : agentShareDisabledReason(server)
    const toolLabel = `${server.tool_count} ${server.tool_count === 1 ? 'tool' : 'tools'}`
    const connectionStatus = connectionState ? agentConnectionStatus(connectionState) : null

    return (
        <Item variant={shared ? 'outline' : 'muted'} size="sm" className={shared ? undefined : 'opacity-70'}>
            <ItemMedia>
                <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="truncate">{server.name}</ItemTitle>
                <ItemDescription className="truncate">
                    {sharedByYou ? `${toolLabel} available to this agent` : (attribution ?? toolLabel)}
                </ItemDescription>
                {sharedByYou && connectionStatus && connectionState !== 'ready' && (
                    <Text size="xs" className="m-0 text-warning-foreground" render={<span />}>
                        {connectionStatus.detail}
                    </Text>
                )}
            </ItemContent>
            <ItemActions className="flex-wrap">
                {sharedByYou && connectionStatus && (
                    <Badge variant={connectionState === 'ready' ? 'success' : 'warning'}>
                        {connectionStatus.label}
                    </Badge>
                )}
                {sharedByYou && share && (
                    <QuillAgentGrantScopeControl accountId={accountId} serverId={server.id} scope={share.yourScope} />
                )}
                {shared && (
                    <QuillGatewayToolPoliciesButton
                        serverId={server.id}
                        scope={`agent:${accountId}`}
                        onOpenServer={onOpenServer}
                    />
                )}
                {sharedByOthers.length > 0 && (
                    <QuillRemoveAllSharesButton
                        accountId={accountId}
                        accountName={accountName}
                        serverId={server.id}
                        serverName={server.name}
                        shareCount={sharedByOthers.length + (sharedByYou ? 1 : 0)}
                    />
                )}
                <Switch
                    checked={sharedByYou}
                    disabledReason={loading ? 'Saving your change' : connectionDisabledReason}
                    aria-label={`${sharedByYou ? 'Stop sharing' : 'Share'} your ${server.name} connection with ${accountName}`}
                    onCheckedChange={(checked: boolean) => {
                        if (canChangeAgentShare(checked, loading, connectionDisabledReason)) {
                            onSetAccess(accountId, server.id, checked)
                        }
                    }}
                />
            </ItemActions>
        </Item>
    )
}
