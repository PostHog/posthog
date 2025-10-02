import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'

import { FeedbackSummary } from '../../components/FeedbackItemScene/FeedbackSummary'
import { feedbackItemSceneLogic } from './feedbackItemSceneLogic'

export const scene: SceneExport = {
    component: FeedbackItemScene,
    logic: feedbackItemSceneLogic,
    paramsToProps: ({ params: { id } }) => {
        return { feedbackItemId: id }
    },
}

export function FeedbackItemScene(): JSX.Element {
    return (
        <SceneContent>
            <Header />
            <FeedbackSummary />
        </SceneContent>
    )
}

const Header = (): JSX.Element => {
    return (
        <>
            <SceneBreadcrumbBackButton
                forceBackTo={{
                    key: 'Feedback',
                    name: 'Feedback',
                    path: '/feedback',
                }}
            />
            <SceneDivider />
        </>
    )
}
