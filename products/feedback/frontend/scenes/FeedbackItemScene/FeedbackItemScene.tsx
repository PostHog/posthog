import { useActions } from 'kea'
import { useEffect } from 'react'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

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
    const { loadFeedbackItem } = useActions(feedbackItemSceneLogic)

    useEffect(() => {
        loadFeedbackItem()
    }, [loadFeedbackItem])

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
            <div className="mb-2">
                <SceneBreadcrumbBackButton
                    forceBackTo={{
                        key: 'Feedback',
                        name: 'Feedback',
                        path: '/feedback',
                    }}
                />
            </div>
            <SceneTitleSection
                name="Feedback item"
                description="Details about a single feedback item"
                resourceType={{
                    type: 'feedback',
                }}
            />
            <SceneDivider />
        </>
    )
}
