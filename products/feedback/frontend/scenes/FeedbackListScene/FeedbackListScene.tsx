import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { FeedbackFilters } from '../../components/FeedbackListScene/FeedbackFilters'
import { FeedbackList } from '../../components/FeedbackListScene/FeedbackList'

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
        <SceneTitleSection
            name="Feedback"
            resourceType={{
                type: 'feedback',
            }}
            description="Understand your users' needs and improve your product"
            actions={
                <LemonButton size="small" to={urls.feedbackConfiguration()} type="secondary" icon={<IconGear />}>
                    Configure
                </LemonButton>
            }
        />
    )
}
