import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

/** Whether requesting the posthog-review GitHub team on a pull request in one repository starts a review. */
export function RepositoryTeamRequestsSwitch({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element {
    const { canEdit } = useValues(reviewHogProjectSettingsLogic)
    const { busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const { setRepositoryTeamRequests } = useActions(reviewHogRepositoriesLogic)

    // Turning it on lets anyone who can write to the repository start reviews, so it stays with admins both ways.
    const disabledReason = !canEdit
        ? 'Only project admins can change this'
        : busyRepositories.includes(entry.full_name)
          ? 'Saving…'
          : undefined

    return (
        <span className="flex items-center gap-1.5">
            <span className="text-xs text-secondary">Team requests</span>
            <LemonSwitch
                aria-label={`Start a review when the posthog-review team is requested in ${entry.full_name}`}
                checked={entry.review_team_requests}
                onChange={(checked) => setRepositoryTeamRequests(entry, checked)}
                tooltip="Requesting the posthog-review GitHub team as a reviewer here starts a review, like an @posthog review comment. The team also needs access to this repository on GitHub."
                disabledReason={disabledReason}
                data-attr="review-hog-repository-team-requests"
            />
        </span>
    )
}
