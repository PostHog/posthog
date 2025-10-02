import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'

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
        <SceneContent>
            <Header />
            <div className="flex flex-row gap-4">
                <div className="w-[70%]">
                    <FeedbackContentTabs />
                </div>
                <div className="w-[30%]">
                    <FeedbackMetadataPanel />
                </div>
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
