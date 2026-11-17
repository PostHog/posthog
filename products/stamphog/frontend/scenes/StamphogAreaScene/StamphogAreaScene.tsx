import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { StamphogTabs } from '../../components/StamphogTabs'
import { AreaFilters } from './AreaFilters'
import { AreaList } from './AreaList'
import { stamphogAreaSceneLogic } from './stamphogAreaSceneLogic'

export const scene: SceneExport = {
    component: StamphogAreaScene,
    logic: stamphogAreaSceneLogic,
}

export function StamphogAreaScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Your area"
                description="What changed in code your team owns, and whether your team saw it before it merged."
                resourceType={{ type: 'stamphog' }}
            />
            <StamphogTabs activeKey="area" />
            <AreaFilters />
            <AreaList />
        </SceneContent>
    )
}

export default StamphogAreaScene
