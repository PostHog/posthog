import { useActions, useValues } from 'kea'

import { sceneFileLogic } from 'lib/components/Scenes/sceneFileLogic'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneMenuBar, SceneMenuBarItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'

import { mcpSetupModeLogic } from './setupMode/mcpSetupModeLogic'
import { SETUP_GUIDE_LABEL } from './setupMode/SetupGuideButton'

const RESOURCE_TYPE = 'mcp-analytics'

export function MCPAnalyticsSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <MCPAnalyticsSceneMenuBarInner />
}

function SetupGuideMenu(): JSX.Element {
    const { openSetupMode } = useActions(mcpSetupModeLogic)
    return (
        <SceneMenuBarMenu label="View" dataAttr={`${RESOURCE_TYPE}-menubar-view`}>
            <SceneMenuBarItem
                opensFloatingUi
                onClick={() => openSetupMode('scene_button')}
                data-attr={`${RESOURCE_TYPE}-menubar-setup-guide`}
            >
                {SETUP_GUIDE_LABEL}
            </SceneMenuBarItem>
        </SceneMenuBarMenu>
    )
}

function MCPAnalyticsSceneMenuBarInner(): JSX.Element {
    const { hasFileItems } = useValues(sceneFileLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`} disabled={!hasFileItems}>
                {hasFileItems && <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />}
            </SceneMenuBarMenu>
            {featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_SETUP_MODE] ? <SetupGuideMenu /> : null}
        </SceneMenuBar>
    )
}
