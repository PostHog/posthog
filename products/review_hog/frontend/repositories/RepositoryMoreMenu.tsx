import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

/** The less common settings of one repository, behind a "..." button. */
export function RepositoryMoreMenu({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element {
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
        <More
            size="xsmall"
            aria-label={`More settings for ${entry.full_name}`}
            data-attr="review-hog-repository-more"
            dropdown={{ closeOnClickInside: false }}
            overlay={
                <LemonMenuOverlay
                    items={[
                        {
                            title: entry.full_name,
                            items: [
                                {
                                    label: () => (
                                        <div className="flex max-w-80 flex-col gap-1 py-1">
                                            <LemonSwitch
                                                fullWidth
                                                label="Deep review for risky PRs"
                                                aria-label={`Deep review for risky pull requests in ${entry.full_name}`}
                                                checked={entry.deep_review_gated_prs}
                                                onChange={(checked) => setRepositoryDeepReviews(entry, checked)}
                                                disabledReason={disabledReason}
                                                data-attr="review-hog-repository-deep-review"
                                            />
                                            <p className="m-0 px-2 text-xs text-secondary">
                                                One Deep automatic review per pull request. It replaces the Standard
                                                review when the pull request breaks this repository's auto-approval
                                                rules for size, restricted paths or tier. It follows the Standard review
                                                when that review finds a must-fix issue.
                                            </p>
                                        </div>
                                    ),
                                },
                            ],
                        },
                    ]}
                />
            }
        />
    )
}
