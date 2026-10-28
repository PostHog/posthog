import { useValues } from 'kea'

import { sceneFileLogic } from 'lib/components/Scenes/sceneFileLogic'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneMenuBar, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'

const RESOURCE_TYPE = 'mcp-analytics'

export function MCPAnalyticsSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <MCPAnalyticsSceneMenuBarInner />
}

function MCPAnalyticsSceneMenuBarInner(): JSX.Element {
    const { hasFileItems } = useValues(sceneFileLogic)

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`} disabled={!hasFileItems}>
                {hasFileItems && <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />}
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
