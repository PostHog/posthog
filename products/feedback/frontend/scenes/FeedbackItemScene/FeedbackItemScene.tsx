import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'

import { FeedbackContentTabs } from '../../components/FeedbackItemScene/FeedbackContentTabs'
import { FeedbackMetadataPanel } from '../../components/FeedbackItemScene/FeedbackMetadataPanel'
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
        <>
            <SceneBreadcrumbBackButton
                className="mb-2"
                forceBackTo={{
                    key: 'Feedback',
                    name: 'Feedback',
                    path: '/feedback',
                }}
            />

            <div className="grid grid-cols-4 gap-4">
                <div className="space-y-2 col-span-3">
                    <FeedbackContentTabs />
                </div>
                <FeedbackMetadataPanel />
            </div>
        </>
    )
}
