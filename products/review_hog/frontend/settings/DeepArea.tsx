import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { FullReviewSettingsSection } from './FullReviewSettingsSection'

export function DeepArea(): JSX.Element {
    return (
        <SceneSection
            title="Deep reviews"
            description="Longer reviews that run on request: the Review button, the posthog-review label, or an Inbox report assigned to you. They cost several times more than Standard."
            titleHelper="These settings apply to the Deep reviews you start. A review someone else starts on your pull request uses their settings, but only your own Resolve setting can push to your branch."
        >
            <FullReviewSettingsSection />
        </SceneSection>
    )
}
