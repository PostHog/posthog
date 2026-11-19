import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { FullReviewSettingsSection } from './FullReviewSettingsSection'
import { ReviewSkillsPanel } from './ReviewSkillsPanel'

export function DeepArea(): JSX.Element {
    return (
        <SceneSection
            title="Deep reviews"
            description="Start with the Review button, an @posthog review --deep comment, or an Inbox report assigned to you. A repository's Deep review switch also makes the automatic review Deep when auto-approval sends the pull request to a person. Uses the settings of whoever starts the review. Costs several times more than Standard."
        >
            <FullReviewSettingsSection />
            <ReviewSkillsPanel />
        </SceneSection>
    )
}
