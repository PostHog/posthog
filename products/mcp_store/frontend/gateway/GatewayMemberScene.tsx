import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSwitch, LemonTag, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ServerIcon } from '../scene/icons'
import { GatewayMemberLogicProps, gatewayMemberLogic } from './gatewayMemberLogic'
import { GatewayRouteGuard } from './GatewayRouteGuard'
import { toProfileUser } from './gatewayUtils'
import { memberServerAccessKey } from './mcpGatewayLogic'

export const scene: SceneExport<(typeof gatewayMemberLogic)['props']> = {
    component: GatewayMemberRouteScene,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function GatewayMemberRouteScene({ id }: GatewayMemberLogicProps): JSX.Element {
    const logicProps: GatewayMemberLogicProps = { id }

    return (
        <GatewayRouteGuard requiresAdmin>
            <BindLogic logic={gatewayMemberLogic} props={logicProps}>
                <GatewayMemberScene {...logicProps} />
            </BindLogic>
        </GatewayRouteGuard>
    )
}

export function GatewayMemberScene({
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
            <SceneContent>
                <BackToTeamButton onBack={onBack} />
                <div className="flex items-center justify-center gap-2 py-8 text-secondary">
                    <Spinner /> Loading member…
                </div>
            </SceneContent>
        )
    }
    if (!member) {
        return (
            <SceneContent>
                <BackToTeamButton onBack={onBack} />
                <div className="py-8 text-center text-secondary">
                    Member not found. Return to team & agents and choose another member.
                </div>
            </SceneContent>
        )
    }

    const memberName =
        [member.user.first_name, member.user.last_name].filter(Boolean).join(' ').trim() || member.user.email
    const firstName = member.user.first_name?.trim() || memberName.split(' ')[0]

    return (
        <SceneContent>
            <BackToTeamButton onBack={onBack} />

            <div className="flex items-start gap-3">
                <ProfilePicture user={toProfileUser(member.user)} size="xl" />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <h1 className="mb-0 truncate">{memberName}</h1>
                        <LemonTag type={member.is_org_admin ? 'highlight' : 'muted'}>
                            {member.is_org_admin ? 'Admin' : 'Member'}
                        </LemonTag>
                    </div>
                    <div className="text-secondary">{member.user.email}</div>
                    <div className="text-xs text-secondary mt-1">
                        {allowedServerCount} of {allServers.length} servers
                    </div>
                </div>
            </div>

            <LemonDivider />

            <div className="flex items-center gap-2">
                <h3 className="mb-0">Server access</h3>
                <LemonTag type="muted" size="small">
                    {allowedServerCount} of {allServers.length}
                </LemonTag>
            </div>
            <div className="border rounded divide-y overflow-hidden">
                {allServers.length === 0 ? (
                    <div className="p-4 text-sm text-secondary">
                        No servers are registered with the gateway yet. Add a server before managing member access.
                    </div>
                ) : (
                    allServers.map((server) => {
                        const isRevoked = revokedServerIds.has(server.id)
                        const memberConnection = memberConnectionsByServerId[server.id]
                        const isConnected = connectedServerIds.has(server.id) || Boolean(memberConnection)
                        const accessLoadingKey = memberServerAccessKey(member.user.id, server.id)
                        const accessLoading = memberServerAccessLoadingKeys.has(accessLoadingKey)
                        return (
                            <div
                                key={server.id}
                                className={`flex items-center gap-3 p-2 ${
                                    isRevoked ? 'bg-surface-secondary opacity-70' : ''
                                }`}
                            >
                                <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
                                <div className="flex-1 min-w-0">
                                    <div className="font-semibold truncate">{server.name}</div>
                                    <div className="text-xs text-secondary">
                                        {isRevoked ? (
                                            `Access turned off for ${firstName}`
                                        ) : isConnected ? (
                                            <span>
                                                Connected
                                                {memberConnection?.last_used_at && (
                                                    <>
                                                        {' · used '}
                                                        <TZLabel time={memberConnection.last_used_at} />
                                                    </>
                                                )}
                                            </span>
                                        ) : (
                                            'Not connected yet'
                                        )}
                                    </div>
                                </div>
                                {!isRevoked && (
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        to={
                                            onOpenServer
                                                ? undefined
                                                : urls.mcpGatewayServer(server.id, `member:${member.user.id}`)
                                        }
                                        onClick={
                                            onOpenServer
                                                ? () => onOpenServer(server.id, `member:${member.user.id}`)
                                                : undefined
                                        }
                                    >
                                        Tool policies
                                    </LemonButton>
                                )}
                                <LemonSwitch
                                    checked={!isRevoked}
                                    loading={accessLoading}
                                    aria-label={`${isRevoked ? 'Restore' : 'Turn off'} ${firstName}'s access to ${
                                        server.name
                                    }`}
                                    onChange={(checked) => {
                                        if (!accessLoading) {
                                            setMemberServerAccess(member.user.id, server.id, checked)
                                        }
                                    }}
                                />
                            </div>
                        )
                    })
                )}
            </div>
        </SceneContent>
    )
}

function BackToTeamButton({ onBack }: { onBack?: () => void }): JSX.Element {
    return (
        <LemonButton
            type="tertiary"
            size="small"
            icon={<IconArrowLeft />}
            onClick={onBack ?? (() => router.actions.push(urls.mcpGatewayTab('team')))}
        >
            Back to team & agents
        </LemonButton>
    )
}
