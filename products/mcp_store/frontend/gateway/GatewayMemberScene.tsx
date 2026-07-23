import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonDivider, LemonSwitch, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ServerIcon } from '../scene/icons'
import { gatewayMemberLogic } from './gatewayMemberLogic'
import { toProfileUser } from './gatewayUtils'
import { memberServerAccessKey } from './mcpGatewayLogic'

export const scene: SceneExport<(typeof gatewayMemberLogic)['props']> = {
    component: GatewayMemberScene,
    logic: gatewayMemberLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function GatewayMemberScene(): JSX.Element {
    const { allServers, member, memberServerAccessLoadingKeys } = useValues(gatewayMemberLogic)
    const { setMemberServerAccess } = useActions(gatewayMemberLogic)

    if (!member) {
        return <SceneContent>Member not found.</SceneContent>
    }

    const connected = new Set(member.connected_server_ids)
    const revoked = new Set(member.revoked_server_ids)

    return (
        <SceneContent>
            <LemonButton size="small" onClick={() => router.actions.push(urls.mcpGatewayTab('team'))}>
                ‹ Back to team & agents
            </LemonButton>

            <div className="flex items-center gap-3">
                <ProfilePicture user={toProfileUser(member.user)} size="xl" />
                <div>
                    <div className="flex items-center gap-2">
                        <h1 className="mb-0">
                            {member.user.first_name} {member.user.last_name}
                        </h1>
                        {member.is_org_admin && <LemonTag type="highlight">admin</LemonTag>}
                    </div>
                    <div className="text-secondary">{member.user.email}</div>
                </div>
            </div>

            <LemonDivider />

            <h3 className="mb-0">Server access</h3>
            <div className="border rounded divide-y">
                {allServers.map((server) => {
                    const isRevoked = revoked.has(server.id)
                    const isConnected = connected.has(server.id)
                    return (
                        <div key={server.id} className="flex items-center gap-3 p-2">
                            <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
                            <div className="flex-1 min-w-0">
                                <div className="font-semibold">{server.name}</div>
                                <div className="text-xs text-secondary">
                                    {isRevoked
                                        ? `Access turned off for ${member.user.first_name}`
                                        : server.auth_mode === 'shared'
                                          ? 'Shared credential — pre-authorized'
                                          : isConnected
                                            ? 'Connected'
                                            : 'Not connected yet'}
                                </div>
                            </div>
                            {isConnected && (
                                <LemonButton size="xsmall" type="secondary" to={urls.mcpGatewayServer(server.id)}>
                                    Tool policies
                                </LemonButton>
                            )}
                            <LemonSwitch
                                checked={!isRevoked}
                                loading={memberServerAccessLoadingKeys.has(
                                    memberServerAccessKey(member.user.id, server.id)
                                )}
                                aria-label={`${isRevoked ? 'Restore' : 'Turn off'} ${member.user.first_name || member.user.email}'s access to ${server.name}`}
                                onChange={(checked) => setMemberServerAccess(member.user.id, server.id, checked)}
                            />
                        </div>
                    )
                })}
            </div>
        </SceneContent>
    )
}
