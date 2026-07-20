import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { GatewayAuditLog } from './GatewayAuditLog'
import { GatewayServersHome } from './GatewayServersHome'
import { GatewayTeamAndAgents } from './GatewayTeamAndAgents'
import { GatewayTeamSettings } from './GatewayTeamSettings'
import { NewTokenModal } from './NewTokenModal'
import { mcpGatewayLogic } from './mcpGatewayLogic'
import { GatewayTab, mcpGatewaySceneLogic } from './mcpGatewaySceneLogic'

export const scene: SceneExport = {
    component: McpGatewayScene,
    logic: mcpGatewaySceneLogic,
}

const TAB_LABELS: Record<GatewayTab, string> = {
    servers: 'Servers',
    team: 'Team & agents',
    settings: 'Team settings',
    audit: 'Audit log',
}

export function McpGatewayScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab, availableTabs } = useValues(mcpGatewaySceneLogic)
    const { setTab } = useActions(mcpGatewaySceneLogic)
    const { isAdmin } = useValues(mcpGatewayLogic)

    if (!featureFlags[FEATURE_FLAGS.MCP_GATEWAY]) {
        return (
            <SceneContent>
                <LemonBanner type="warning">The MCP gateway is not enabled for this project.</LemonBanner>
            </SceneContent>
        )
    }

    const tabContent: Record<GatewayTab, JSX.Element> = {
        servers: <GatewayServersHome />,
        team: <GatewayTeamAndAgents />,
        settings: <GatewayTeamSettings />,
        audit: <GatewayAuditLog />,
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.McpGateway].name}
                description="Every MCP server your team runs through the gateway. Route people and agents through one control plane."
                resourceType={{ type: sceneConfigurations[Scene.McpGateway].iconType || 'default_icon_type' }}
            />
            {isAdmin ? (
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setTab(key)}
                    sceneInset
                    tabs={availableTabs.map((tab) => ({
                        key: tab,
                        label: TAB_LABELS[tab],
                        content: tabContent[tab],
                    }))}
                />
            ) : (
                <GatewayServersHome />
            )}
            <NewTokenModal />
        </SceneContent>
    )
}
