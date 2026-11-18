import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { CodeReviewReviewsTableRetrieveReviewMode, CodeReviewReviewsTableRetrieveStatus } from './generated/api.schemas'
import { REVIEW_MODE_LABEL } from './reviewDisplay'
import { reviewHogSettingsLogic } from './reviewHogSettingsLogic'

const MODE_OPTIONS = [
    { value: null, label: 'All modes' },
    {
        value: CodeReviewReviewsTableRetrieveReviewMode.Flash,
        label: REVIEW_MODE_LABEL[CodeReviewReviewsTableRetrieveReviewMode.Flash],
    },
    {
        value: CodeReviewReviewsTableRetrieveReviewMode.Full,
        label: REVIEW_MODE_LABEL[CodeReviewReviewsTableRetrieveReviewMode.Full],
    },
]

const STATUS_OPTIONS = [
    { value: null, label: 'All statuses' },
    { value: CodeReviewReviewsTableRetrieveStatus.Running, label: 'Running' },
    { value: CodeReviewReviewsTableRetrieveStatus.Completed, label: 'Completed' },
]

const PUBLISHED_OPTIONS = [
    { value: null, label: 'Posted or not' },
    { value: true, label: 'Posted' },
    { value: false, label: 'Not posted' },
]

export function ReviewsFilters(): JSX.Element {
    const { reviewsPage, reviewsRepository, reviewsRepositoryOptions, reviewsMode, reviewsStatus, reviewsPublished } =
        useValues(reviewHogSettingsLogic)
    const { setReviewsRepository, setReviewsMode, setReviewsStatus, setReviewsPublished } =
        useActions(reviewHogSettingsLogic)

    const runningCount = reviewsPage?.running_count ?? 0
    const runningActive = reviewsStatus === CodeReviewReviewsTableRetrieveStatus.Running

    return (
        <div className="@container/reviews-filters">
            <div className="grid grid-cols-2 gap-2 @min-[44rem]/reviews-filters:flex @min-[44rem]/reviews-filters:flex-wrap @min-[44rem]/reviews-filters:items-center">
                {(runningCount > 0 || runningActive) && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        active={runningActive}
                        onClick={() =>
                            setReviewsStatus(runningActive ? null : CodeReviewReviewsTableRetrieveStatus.Running)
                        }
                        tooltip={runningActive ? 'Show every review' : 'Show only running reviews'}
                        data-attr="code-review-reviews-running-filter"
                    >
                        <span>{`Running · ${runningCount}`}</span>
                    </LemonButton>
                )}
                <LemonSelect
                    size="small"
                    value={reviewsRepository}
                    onChange={setReviewsRepository}
                    options={[
                        { value: null, label: 'All repositories' },
                        ...reviewsRepositoryOptions.map((repository) => ({ value: repository, label: repository })),
                    ]}
                    className="col-span-2 min-w-0 @min-[44rem]/reviews-filters:min-w-52"
                    data-attr="code-review-reviews-repository-filter"
                />
                <LemonSelect
                    size="small"
                    value={reviewsMode}
                    onChange={setReviewsMode}
                    options={MODE_OPTIONS}
                    data-attr="code-review-reviews-mode-filter"
                />
                <LemonSelect
                    size="small"
                    value={reviewsStatus}
                    onChange={setReviewsStatus}
                    options={STATUS_OPTIONS}
                    data-attr="code-review-reviews-status-filter"
                />
                <LemonSelect
                    size="small"
                    value={reviewsPublished}
                    onChange={setReviewsPublished}
                    options={PUBLISHED_OPTIONS}
                    data-attr="code-review-reviews-posted-filter"
                />
            </div>
        </div>
    )
}
