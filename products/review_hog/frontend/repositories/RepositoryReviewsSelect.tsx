import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSelectOptionLeaf } from '@posthog/lemon-ui'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { RepositoryReviews, reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

type ReviewsKey = 'ready' | 'ready_pushes' | 'drafts_ready' | 'drafts_ready_pushes'

interface ReviewsOption {
    key: ReviewsKey
    reviews: RepositoryReviews
    label: string
    labelInMenu: string
    tooltip: string
}

const READY_OPTIONS: ReviewsOption[] = [
    {
        key: 'ready',
        reviews: { review_drafts: false, review_pushes: false },
        label: 'When ready',
        labelInMenu: 'When ready',
        tooltip: 'One review when the pull request is ready for review.',
    },
    {
        key: 'ready_pushes',
        reviews: { review_drafts: false, review_pushes: true },
        label: 'When ready + pushes',
        labelInMenu: 'When ready + pushes',
        tooltip: 'One review when the pull request is ready for review, then later pushes that are worth a review.',
    },
]
const DRAFTS_OPTIONS: ReviewsOption[] = [
    {
        key: 'drafts_ready',
        reviews: { review_drafts: true, review_pushes: false },
        label: 'When ready + drafts',
        labelInMenu: 'When ready',
        tooltip: 'One review when a draft opens, and one more when it is marked ready.',
    },
    {
        key: 'drafts_ready_pushes',
        reviews: { review_drafts: true, review_pushes: true },
        label: 'When ready + pushes + drafts',
        labelInMenu: 'When ready + pushes',
        tooltip:
            'One review when a draft opens, one when it is marked ready, then later pushes that are worth a review.',
    },
]
const ALL_OPTIONS = [...READY_OPTIONS, ...DRAFTS_OPTIONS]

function keyOf(entry: ReviewRepositoryOverviewEntryApi): ReviewsKey {
    const match = ALL_OPTIONS.find(
        (option) =>
            option.reviews.review_drafts === entry.review_drafts && option.reviews.review_pushes === entry.review_pushes
    )
    return match?.key ?? 'ready'
}

/** Whether picking `option` turns off a review the repository has, which only admins may do. */
function turnsReviewsDown(entry: ReviewRepositoryOverviewEntryApi, option: ReviewsOption): boolean {
    return (
        (entry.review_drafts && !option.reviews.review_drafts) || (entry.review_pushes && !option.reviews.review_pushes)
    )
}

/** When pull requests in one repository get automatic reviews: when ready, on later pushes, and when a draft opens. */
export function RepositoryReviewsSelect({ entry }: { entry: ReviewRepositoryOverviewEntryApi }): JSX.Element {
    const { canEdit } = useValues(reviewHogProjectSettingsLogic)
    const { busyRepositories } = useValues(reviewHogRepositoriesLogic)
    const { setRepositoryReviews } = useActions(reviewHogRepositoriesLogic)

    const toLeaf = (option: ReviewsOption): LemonSelectOptionLeaf<ReviewsKey> => ({
        value: option.key,
        label: option.label,
        labelInMenu: option.labelInMenu,
        tooltip: option.tooltip,
        disabledReason:
            !canEdit && turnsReviewsDown(entry, option) ? 'Only project admins can turn reviews down' : undefined,
    })

    return (
        <span className="flex items-center gap-1.5">
            <span className="text-xs text-secondary">Reviews</span>
            <LemonSelect<ReviewsKey>
                size="xsmall"
                aria-label={`Automatic reviews in ${entry.full_name}`}
                value={keyOf(entry)}
                options={[
                    { title: 'Ready for review', options: READY_OPTIONS.map(toLeaf) },
                    { title: 'Ready for review, plus drafts', options: DRAFTS_OPTIONS.map(toLeaf) },
                ]}
                onChange={(key) => {
                    const option = ALL_OPTIONS.find((candidate) => candidate.key === key)
                    if (option && key !== keyOf(entry)) {
                        setRepositoryReviews(entry, option.reviews)
                    }
                }}
                disabledReason={busyRepositories.includes(entry.full_name) ? 'Saving…' : undefined}
                data-attr="review-hog-repository-reviews"
            />
        </span>
    )
}
