import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { FullReviewSettingsSection } from './FullReviewSettingsSection'
import { ReviewSkillsPanel } from './ReviewSkillsPanel'

export function DeepArea(): JSX.Element {
    return (
        <SceneSection
            title="Deep reviews"
            description="Start with the Review button, an @posthog review --deep comment, or an Inbox report assigned to you. Repositories can also run Deep automatically when auto-approval requires a human review. Uses the settings of whoever starts the review. Costs several times more than Standard."
        >
            <FullReviewSettingsSection />
            <ReviewSkillsPanel />
        </SceneSection>
    )
}
