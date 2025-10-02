import { useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'

import { FeedbackSummary } from '../../components/FeedbackItemScene/FeedbackSummary'
import { FeedbackDiscussions } from './FeedbackDiscussions'
import { feedbackItemSceneLogic } from './feedbackItemSceneLogic'

export const scene: SceneExport = {
    component: FeedbackItemScene,
    logic: feedbackItemSceneLogic,
    paramsToProps: ({ params: { id } }) => {
        return { feedbackItemId: id }
    },
}

export function FeedbackItemScene(): JSX.Element {
    const { feedbackItem } = useValues(feedbackItemSceneLogic)

    return (
        <SceneContent>
            <Header />
            <div className="flex flex-row gap-4">
                <div className="w-1/2">
                    <FeedbackSummary />
                </div>
                {feedbackItem && (
                    <div className="w-1/2">
                        <FeedbackDiscussions feedbackItemId={feedbackItem.id} />
                    </div>
                )}
            </div>
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
