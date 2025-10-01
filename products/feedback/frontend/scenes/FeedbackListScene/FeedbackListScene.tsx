import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { FeedbackFilters } from '../../components/FeedbackFilters'
import { FeedbackList } from '../../components/ListScene/FeedbackList'

export const scene: SceneExport = {
    component: FeedbackListScene,
}

export function FeedbackListScene(): JSX.Element {
    return (
        <SceneContent>
            <Header />
            <FeedbackFilters />
            <FeedbackList />
        </SceneContent>
    )
}

const Header = (): JSX.Element => {
    return (
        <>
            <SceneTitleSection
                name="Feedback"
                description="See what your users like and don't like"
                resourceType={{
                    type: 'feedback',
                }}
            />
            <SceneDivider />
        </>
    )
}
