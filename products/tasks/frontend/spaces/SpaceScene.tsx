import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { TodayQuillRoot } from '~/layout/today/TodayQuillRoot'
import { spaceLabel } from '~/layout/today/todaySpacesLogic'

import { SpaceFeed } from './SpaceFeed'
import { SpaceSceneLogicProps, spaceSceneLogic } from './spaceSceneLogic'

export const scene: SceneExport<SpaceSceneLogicProps> = {
    component: SpaceScene,
    logic: spaceSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function SpaceScene({ id }: SpaceSceneLogicProps): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { space, spaceLoading, spaceUnavailable } = useValues(spaceSceneLogic({ id }))

    if (!enabled || spaceUnavailable) {
        return <NotFound object="space" />
    }
    return (
        <SceneContent>
            <SceneTitleSection
                name={space ? spaceLabel(space) : null}
                isLoading={spaceLoading && !space}
                resourceType={{ type: 'task' }}
            />
            <TodayQuillRoot>
                <SpaceFeed id={id} />
            </TodayQuillRoot>
        </SceneContent>
    )
}
