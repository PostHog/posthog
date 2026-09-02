import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { gatewayAgentLogic } from '../gateway/gatewayAgentLogic'
import { GatewayAgentScene } from '../gateway/GatewayAgentScene'
import { GatewayAuditLog } from '../gateway/GatewayAuditLog'
import { gatewayMemberLogic } from '../gateway/gatewayMemberLogic'
import { GatewayMemberScene } from '../gateway/GatewayMemberScene'
import { gatewayServerLogic } from '../gateway/gatewayServerLogic'
import { GatewayServerScene } from '../gateway/GatewayServerScene'
import { GatewayServersHome } from '../gateway/GatewayServersHome'
import { GatewayTeamAndAgents } from '../gateway/GatewayTeamAndAgents'
import { GatewayTeamSettings } from '../gateway/GatewayTeamSettings'
import { GatewayTab } from '../gateway/mcpGatewaySceneLogic'
import { mcpGatewaySettingsLogic } from './mcpGatewaySettingsLogic'

const TAB_LABELS: Record<GatewayTab, string> = {
    servers: 'Servers',
    team: 'Team & agents',
    settings: 'Team settings',
    audit: 'Audit log',
}

export function McpGatewaySettings(): JSX.Element {
    const { activeTab, availableTabs, configLoadFailed, detailId, detailScope, detailView, permissionsInitialized } =
        useValues(mcpGatewaySettingsLogic)
    const { closeDetail, openAgent, openMember, openServer, setTab } = useActions(mcpGatewaySettingsLogic)

    if (!permissionsInitialized) {
        return (
            <div className="flex items-center gap-2 text-secondary">
                <Spinner /> Loading MCP server settings
            </div>
        )
    }

    const serverContent =
        detailView === 'server' && detailId ? (
            <BindLogic
                logic={gatewayServerLogic}
                props={{ id: detailId, initialScope: detailScope ?? undefined, settingsMode: true }}
            >
                <GatewayServerScene id={detailId} onBack={() => closeDetail('servers')} />
            </BindLogic>
        ) : (
            <GatewayServersHome onOpenServer={openServer} />
        )
    const teamContent =
        detailView === 'agent' && detailId ? (
            <BindLogic logic={gatewayAgentLogic} props={{ id: detailId }}>
                <GatewayAgentScene
                    id={detailId}
                    onBack={() => closeDetail('team')}
                    onOpenServer={(serverId, scope) => openServer(serverId, scope)}
                />
            </BindLogic>
        ) : detailView === 'member' && detailId ? (
            <BindLogic logic={gatewayMemberLogic} props={{ id: detailId }}>
                <GatewayMemberScene
                    id={detailId}
                    onBack={() => closeDetail('team')}
                    onOpenServer={(serverId, scope) => openServer(serverId, scope)}
                />
            </BindLogic>
        ) : (
            <GatewayTeamAndAgents onOpenAgent={openAgent} onOpenMember={openMember} />
        )
    const tabContent: Record<GatewayTab, JSX.Element> = {
        servers: serverContent,
        team: teamContent,
        settings: <GatewayTeamSettings onOpenServer={openServer} />,
        audit: <GatewayAuditLog />,
    }

    return (
        <div className="flex flex-col gap-4">
            {configLoadFailed && (
                <LemonBanner type="warning">
                    Couldn't load MCP server access. Refresh the page to try again.
                </LemonBanner>
            )}
            <LemonTabs
                activeKey={activeTab}
                onChange={setTab}
                tabs={availableTabs.map((tab) => ({
                    key: tab,
                    label: TAB_LABELS[tab],
                    content: tabContent[tab],
                }))}
            />
        </div>
    )
}
