import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

/** Whether draft pull requests in one repository get their automatic review when they open. */
export function RepositoryDraftsSwitch({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element {
    const { canEdit } = useValues(reviewHogProjectSettingsLogic)
    const { busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const { setRepositoryDrafts } = useActions(reviewHogRepositoriesLogic)

    const disabledReason =
        !canEdit && entry.review_drafts
            ? 'Only project admins can turn this off'
            : busyRepositories.includes(entry.full_name)
              ? 'Saving…'
              : undefined

    return (
        <span className="flex items-center gap-1.5">
            <span className="text-xs text-secondary">Drafts</span>
            <LemonSwitch
                aria-label={`Review drafts in ${entry.full_name}`}
                checked={entry.review_drafts}
                onChange={(checked) => setRepositoryDrafts(entry, checked)}
                tooltip="Drafts here get one automatic review when they open."
                disabledReason={disabledReason}
                data-attr="review-hog-repository-drafts"
            />
        </span>
    )
}
