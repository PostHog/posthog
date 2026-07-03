import { useValues } from 'kea'

import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
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
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const hasFileItems = !!projectTreeRefEntry

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`} disabled={!hasFileItems}>
                {hasFileItems && <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />}
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
