import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { StamphogTabs } from '../../components/StamphogTabs'
import { stamphogTeamViewSceneLogic } from './stamphogTeamViewSceneLogic'
import { TeamViewFilters } from './TeamViewFilters'
import { TeamViewTable } from './TeamViewTable'

export const scene: SceneExport = {
    component: StamphogTeamViewScene,
    logic: stamphogTeamViewSceneLogic,
}

export function StamphogTeamViewScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Team view"
                description="Pull requests that changed code a team owns, and what reviewer routing decided for that team."
                resourceType={{ type: 'stamphog' }}
            />
            <StamphogTabs activeKey="team" />
            <TeamViewFilters />
            <TeamViewTable />
        </SceneContent>
    )
}

export default StamphogTeamViewScene
