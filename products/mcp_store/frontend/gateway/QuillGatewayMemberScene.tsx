import { useActions, useValues } from 'kea'

import {
    Badge,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Heading,
    ItemGroup,
    Separator,
    Skeleton,
    Text,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'

import { GatewayMemberLogicProps, gatewayMemberLogic } from './gatewayMemberLogic'
import { gatewayMemberNames } from './GatewayMemberScene'
import { memberServerAccessKey } from './mcpGatewayLogic'
import { QuillGatewayBackToTeamButton } from './QuillGatewayBackToTeamButton'
import { QuillGatewayMemberServerRow } from './QuillGatewayMemberServerRow'

export function QuillGatewayMemberScene({
    onBack,
    onOpenServer,
}: {
    id: GatewayMemberLogicProps['id']
    onBack?: () => void
    onOpenServer?: (serverId: string, scope: string) => void
}): JSX.Element {
    const {
        allowedServerCount,
        allServers,
        allServersInitialized,
        connectedServerIds,
        member,
        memberConnectionsByServerId,
        memberInitialized,
        memberLoading,
        memberServerAccessLoadingKeys,
        revokedServerIds,
    } = useValues(gatewayMemberLogic)
    const { setMemberServerAccess } = useActions(gatewayMemberLogic)

    if (!allServersInitialized || (!member && (!memberInitialized || memberLoading))) {
        return (
            <div className="flex flex-col gap-4" role="status" aria-label="Loading member…" aria-busy>
                <QuillGatewayBackToTeamButton onBack={onBack} />
                <Skeleton className="h-14" />
                <Skeleton className="h-32" />
            </div>
        )
    }

    if (!member) {
        return (
            <div className="flex flex-col gap-4">
                <QuillGatewayBackToTeamButton onBack={onBack} />
                <Empty>
                    <EmptyHeader>
                        <EmptyDescription>
                            Member not found. Return to team & agents and choose another member.
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    const { memberName, firstName } = gatewayMemberNames(member)
    const serverCountLabel = `${allowedServerCount} of ${allServers.length}`

    return (
        <div className="flex min-w-0 flex-col gap-4">
            <QuillGatewayBackToTeamButton onBack={onBack} />

            <div className="flex items-start gap-3">
                <QuillPersonAvatar name={memberName} email={member.user.email} size="default" />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <Heading size="base" render={<h3 className="m-0 truncate" />}>
                            {memberName}
                        </Heading>
                        <Badge variant={member.is_org_admin ? 'info' : 'default'}>
                            {member.is_org_admin ? 'Admin' : 'Member'}
                        </Badge>
                    </div>
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        {member.user.email}
                    </Text>
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        {`${serverCountLabel} servers`}
                    </Text>
                </div>
            </div>

            <Separator />

            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Server access
                    </Heading>
                    <Badge>{serverCountLabel}</Badge>
                </div>
                {allServers.length === 0 ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyDescription>
                                No servers are registered with the gateway yet. Add a server before managing member
                                access.
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                ) : (
                    <ItemGroup combined>
                        {allServers.map((server) => {
                            const memberConnection = memberConnectionsByServerId[server.id]
                            const accessLoading = memberServerAccessLoadingKeys.has(
                                memberServerAccessKey(member.user.id, server.id)
                            )

                            return (
                                <QuillGatewayMemberServerRow
                                    key={server.id}
                                    server={server}
                                    memberId={member.user.id}
                                    firstName={firstName}
                                    isRevoked={revokedServerIds.has(server.id)}
                                    isConnected={connectedServerIds.has(server.id) || Boolean(memberConnection)}
                                    lastUsedAt={memberConnection?.last_used_at}
                                    accessLoading={accessLoading}
                                    onSetAccess={(checked) => setMemberServerAccess(member.user.id, server.id, checked)}
                                    onOpenServer={onOpenServer}
                                />
                            )
                        })}
                    </ItemGroup>
                )}
            </div>
        </div>
    )
}
