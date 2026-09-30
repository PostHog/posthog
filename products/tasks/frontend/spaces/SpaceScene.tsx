import { useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
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
            <LemonTabs activeKey="feed" tabs={[{ key: 'feed', label: 'Feed', content: <SpaceFeed id={id} /> }]} />
        </SceneContent>
    )
}
