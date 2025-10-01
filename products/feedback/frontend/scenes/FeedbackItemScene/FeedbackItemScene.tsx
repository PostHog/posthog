import { useActions } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'

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
            <SceneTitleSection
                name="Feedback item"
                description="Details about a single feedback item"
                resourceType={{
                    type: 'feedback',
                }}
            />
            <div className="flex items-center gap-2 px-6 mb-4">
                <Link to="/feedback">
                    <IconArrowLeft /> Back to Feedback
                </Link>
            </div>
            <SceneDivider />
        </>
    )
}
