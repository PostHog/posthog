import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { GatewayAuditLog } from './GatewayAuditLog'
import { GatewayRail } from './GatewayRail'
import { GatewayServersHome } from './GatewayServersHome'
import { GatewayTeamAndAgents } from './GatewayTeamAndAgents'
import { GatewayTeamSettings } from './GatewayTeamSettings'
import { GatewayTab, mcpGatewaySceneLogic } from './mcpGatewaySceneLogic'

export const scene: SceneExport = {
    component: McpGatewayScene,
    logic: mcpGatewaySceneLogic,
}

export function McpGatewayScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab, availableTabs } = useValues(mcpGatewaySceneLogic)

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
        <SceneContent className="pt-4">
            <SceneTitleSection
                name={sceneConfigurations[Scene.McpGateway].name}
                description="Every MCP server your team runs through the gateway. Route people and agents through one control plane."
                resourceType={{ type: sceneConfigurations[Scene.McpGateway].iconType || 'default_icon_type' }}
            />
            <div className="flex items-start gap-6">
                <GatewayRail />
                <div className="min-w-0 flex-1">{availableTabs.includes(activeTab) ? tabContent[activeTab] : null}</div>
            </div>
        </SceneContent>
    )
}
