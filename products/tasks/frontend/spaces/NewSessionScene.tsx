import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { newSessionSceneLogic } from './newSessionSceneLogic'
import { NewSessionStart } from './NewSessionStart'

export const scene: SceneExport = {
    component: NewSessionScene,
    logic: newSessionSceneLogic,
}

export function NewSessionScene(): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')

    if (!enabled) {
        return <NotFound object="page" />
    }

    return (
        <SceneContent className="flex-1">
            <NewSessionStart heading="What do you want to work on?" surface="new_session" />
        </SceneContent>
    )
}
