import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { FullReviewSettingsSection } from './FullReviewSettingsSection'
import { ReviewSkillsPanel } from './ReviewSkillsPanel'

export function DeepArea(): JSX.Element {
    return (
        <SceneSection
            title="Deep · only when someone asks"
            description="Deep runs when someone asks: the Review button, the posthog-review label, or an Inbox report assigned to you. It uses the skills and threshold you pick here, and costs several times more than Standard. Everything here applies only to Deep reviews. A review someone else starts on your PR uses their settings, but only your own Resolve choice can push to your branch."
        >
            <FullReviewSettingsSection />
            <ReviewSkillsPanel />
        </SceneSection>
    )
}
