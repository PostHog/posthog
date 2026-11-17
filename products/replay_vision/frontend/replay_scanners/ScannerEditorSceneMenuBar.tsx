import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { replayVisionFeedbackAction } from '../components/replayVisionFeedbackAction'

const RESOURCE_TYPE = 'replay-scanner-editor'

export function ScannerEditorSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ScannerEditorSceneMenuBarInner /> : null
}

function ScannerEditorSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [replayVisionFeedbackAction(RESOURCE_TYPE, { order: 1, variant: 'secondary' })]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
