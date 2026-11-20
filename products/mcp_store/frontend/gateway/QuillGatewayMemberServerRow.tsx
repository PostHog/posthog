import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle, Switch } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { MCPGatewayServerApi } from '../generated/api.schemas'
import { ServerIcon } from '../scene/icons'
import { QuillGatewayToolPoliciesButton } from './QuillGatewayToolPoliciesButton'

export function QuillGatewayMemberServerRow({
    server,
    memberId,
    firstName,
    isRevoked,
    isConnected,
    lastUsedAt,
    accessLoading,
    onSetAccess,
    onOpenServer,
}: {
    server: MCPGatewayServerApi
    memberId: number
    firstName: string
    isRevoked: boolean
    isConnected: boolean
    lastUsedAt?: string | null
    accessLoading: boolean
    onSetAccess: (checked: boolean) => void
    onOpenServer?: (serverId: string, scope: string) => void
}): JSX.Element {
    return (
        <Item variant={isRevoked ? 'muted' : 'outline'} size="sm" className={isRevoked ? 'opacity-70' : undefined}>
            <ItemMedia>
                <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle className="truncate">{server.name}</ItemTitle>
                <ItemDescription>
                    {isRevoked ? (
                        `Access turned off for ${firstName}`
                    ) : isConnected ? (
                        <span>
                            Connected
                            {lastUsedAt && (
                                <>
                                    {' · used '}
                                    <TZLabel time={lastUsedAt} />
                                </>
                            )}
                        </span>
                    ) : (
                        'Not connected yet'
                    )}
                </ItemDescription>
            </ItemContent>
            <ItemActions className="flex-wrap">
                {!isRevoked && (
                    <QuillGatewayToolPoliciesButton
                        serverId={server.id}
                        scope={`member:${memberId}`}
                        onOpenServer={onOpenServer}
                    />
                )}
                <Switch
                    checked={!isRevoked}
                    disabledReason={accessLoading ? 'Saving your change' : undefined}
                    aria-label={`${isRevoked ? 'Restore' : 'Turn off'} ${firstName}'s access to ${server.name}`}
                    onCheckedChange={(checked: boolean) => {
                        if (!accessLoading) {
                            onSetAccess(checked)
                        }
                    }}
                />
            </ItemActions>
        </Item>
    )
}
