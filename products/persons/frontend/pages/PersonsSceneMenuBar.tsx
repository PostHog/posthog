import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SceneMenuBar, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'

export function PersonsSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!sceneMenuBarEnabled) {
        return null
    }

    if (todayRailNav) {
        // This page has no project tree entry, so it has no File menu. The bar adds Help under the Today layout.
        return <SceneMenuBar />
    }

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr="persons-menubar-file">
                <SceneMenuBarFileItems dataAttrKey="persons" />
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
