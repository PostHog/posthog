import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { FullReviewSettingsSection } from './FullReviewSettingsSection'
import { ReviewSkillsPanel } from './ReviewSkillsPanel'

export function DeepArea(): JSX.Element {
    return (
        <SceneSection
            title="Deep reviews"
            description="Start with the Review button, an @posthog review --deep comment, or an Inbox report assigned to you. A repository can also run a Deep automatic review after a Standard review that finds a must-fix issue, and on pull requests that break its auto-approval rules. Uses the settings of whoever starts the review. Costs several times more than Standard."
        >
            <FullReviewSettingsSection />
            <ReviewSkillsPanel />
        </SceneSection>
    )
}
