import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

/** Whether a large or sensitive pull request, by the repository's auto-approval rules, gets a Deep automatic review. */
export function RepositoryDeepReviewSwitch({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element | null {
    const { canEdit } = useValues(reviewHogProjectSettingsLogic)
    const { busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const { setRepositoryDeepReviews } = useActions(reviewHogRepositoriesLogic)

    // Without auto-approval the repository has no rules to read. A switch left on stays visible so an admin can turn it off.
    if (!entry.auto_approval && !entry.deep_review_gated_prs) {
        return null
    }

    const disabledReason =
        !canEdit && entry.deep_review_gated_prs
            ? 'Only project admins can turn this off'
            : busyRepositories.includes(entry.full_name)
              ? 'Saving…'
              : undefined

    return (
        <span className="flex items-center gap-1.5">
            <span className="text-xs whitespace-nowrap text-secondary">Deep review for large or sensitive PRs</span>
            <LemonSwitch
                aria-label={`Deep review for large or sensitive pull requests in ${entry.full_name}`}
                checked={entry.deep_review_gated_prs}
                onChange={(checked) => setRepositoryDeepReviews(entry, checked)}
                tooltip="Large or sensitive means the pull request breaks this repository's auto-approval rules for size, restricted paths or tier. Its automatic review is then a Deep review, once per pull request."
                disabledReason={disabledReason}
                data-attr="review-hog-repository-deep-review"
            />
        </span>
    )
}
