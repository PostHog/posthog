import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

/** Whether a pull request that auto-approval sends to a person gets its automatic review as a Deep review. */
export function RepositoryDeepReviewSwitch({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element {
    const { canEdit } = useValues(reviewHogProjectSettingsLogic)
    const { busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const { setRepositoryDeepReviews } = useActions(reviewHogRepositoriesLogic)

    const disabledReason =
        !canEdit && entry.deep_review_gated_prs
            ? 'Only project admins can turn this off'
            : busyRepositories.includes(entry.full_name)
              ? 'Saving…'
              : undefined

    return (
        <span className="flex items-center gap-1.5">
            <span className="text-xs text-secondary">Deep review</span>
            <LemonSwitch
                aria-label={`Deep review for pull requests that need a person in ${entry.full_name}`}
                checked={entry.deep_review_gated_prs}
                onChange={(checked) => setRepositoryDeepReviews(entry, checked)}
                tooltip="A pull request that auto-approval's size, path or tier rules send to a person gets its automatic review as a Deep review instead of a Standard one. The repository must also be added to auto-approval."
                disabledReason={disabledReason}
                data-attr="review-hog-repository-deep-review"
            />
        </span>
    )
}
