import { AreaHeader } from './AreaHeader'
import { FullReviewSettingsSection } from './FullReviewSettingsSection'
import { ReviewSkillsPanel } from './ReviewSkillsPanel'

export function DeepArea(): JSX.Element {
    return (
        <section className="flex flex-col gap-3 border-t border-primary pt-6">
            <AreaHeader title="Deep" subtitle="only when someone asks">
                <p className="m-0 text-sm">
                    Deep is a longer review for changes that need extra care: the Review button, the reviewhog label, or
                    an Inbox report assigned to you. It adds the perspectives, quality bar and threshold you pick here,
                    and can fix review comments on your branch if you turn Resolve on. It takes longer and costs several
                    times more than Standard.
                </p>
                <p className="m-0 text-xs text-secondary">
                    Everything in this area applies only to Deep reviews. A review someone else starts on your PR uses
                    their settings, but only your own Resolve choice can push to your branch.
                </p>
            </AreaHeader>
            <FullReviewSettingsSection />
            <ReviewSkillsPanel />
        </section>
    )
}
