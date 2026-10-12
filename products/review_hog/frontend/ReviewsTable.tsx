import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { ReviewHogReviewsListScope, type ReviewRecentReviewApi } from './generated/api.schemas'
import { reviewTitle, runningStageLabel } from './reviewDisplay'
import { REVIEWS_PAGE_SIZE, reviewHogSettingsLogic } from './reviewHogSettingsLogic'
import { ReviewModeTag } from './ReviewModeTag'

const COUNT_CHIPS: {
    key: 'must_fix_count' | 'should_fix_count' | 'consider_count'
    label: string
    dot: string
    text: string
}[] = [
    { key: 'must_fix_count', label: 'must fix', dot: 'bg-danger', text: 'text-danger' },
    { key: 'should_fix_count', label: 'should fix', dot: 'bg-warning', text: 'text-warning' },
    { key: 'consider_count', label: 'consider', dot: 'bg-border-bold', text: 'text-secondary' },
]

/** A first review still running has no completed turn: no findings, no posted state, no drawer. */
function hasCompletedTurn(review: ReviewRecentReviewApi): boolean {
    return review.run_count > 0
}

function FindingCounts({ review }: { review: ReviewRecentReviewApi }): JSX.Element {
    const total = review.must_fix_count + review.should_fix_count + review.consider_count
    if (total === 0) {
        return <span className="text-xs text-secondary">No findings</span>
    }
    return (
        <span className="flex items-center gap-2.5 text-xs">
            {COUNT_CHIPS.filter((chip) => review[chip.key] > 0).map((chip) => (
                <span key={chip.key} className="flex items-center gap-1 whitespace-nowrap">
                    <span className={`size-1.5 rounded-full ${chip.dot}`} />
                    <span className={`font-semibold tabular-nums ${chip.text}`}>{review[chip.key]}</span>
                    <span className="text-secondary">{chip.label}</span>
                </span>
            ))}
        </span>
    )
}

function ReviewStatus({ review }: { review: ReviewRecentReviewApi }): JSX.Element {
    if (review.in_progress) {
        return (
            <span className="flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-warning">
                <Spinner className="text-sm" />
                <span>{runningStageLabel(review)}</span>
            </span>
        )
    }
    const total = review.must_fix_count + review.should_fix_count + review.consider_count
    const color = review.must_fix_count > 0 ? 'bg-danger' : total > 0 ? 'bg-warning' : 'bg-success'
    return <span className={`inline-block size-2 rounded-full ${color}`} />
}

function ReviewsEmptyState(): JSX.Element {
    const { reviewsScope, reviewsFiltered } = useValues(reviewHogSettingsLogic)
    const { setReviewsScope, clearReviewsFilters } = useActions(reviewHogSettingsLogic)
    if (reviewsFiltered) {
        return (
            <div className="flex flex-col items-center gap-2 py-4">
                <span>No reviews match these filters.</span>
                <LemonButton type="secondary" size="small" onClick={() => clearReviewsFilters()}>
                    Clear filters
                </LemonButton>
            </div>
        )
    }
    if (reviewsScope === ReviewHogReviewsListScope.Mine) {
        return (
            <div className="flex flex-col items-center gap-2 py-4">
                <span>No reviews of your pull requests or reviews you started yet.</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => setReviewsScope(ReviewHogReviewsListScope.Everyone)}
                >
                    Show everyone's reviews
                </LemonButton>
            </div>
        )
    }
    return <span>No reviews in this project yet. Paste a pull request URL above to start one.</span>
}

export function ReviewsTable(): JSX.Element {
    const { reviewsPage, reviewsFailed, reviewsCurrentPage, reviewsScope } = useValues(reviewHogSettingsLogic)
    const { setReviewsPage, loadReviews, openReviewDetail } = useActions(reviewHogSettingsLogic)

    if (reviewsFailed && !reviewsPage) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadReviews() }}
                data-attr="code-review-reviews-error"
            >
                Couldn't load reviews. Try again, and if it keeps failing, refresh the page.
            </LemonBanner>
        )
    }

    const columns: LemonTableColumns<ReviewRecentReviewApi> = [
        {
            title: 'Status',
            key: 'status',
            width: 0,
            render: (_, review) => <ReviewStatus review={review} />,
        },
        {
            title: 'Pull request',
            key: 'pull_request',
            render: (_, review) => (
                <div className="flex min-w-0 items-center gap-2">
                    <Link
                        to={review.github_url}
                        target="_blank"
                        className="shrink-0 font-mono text-xs"
                        // The row opens the drawer; the number goes to GitHub instead.
                        onClick={(event) => event.stopPropagation()}
                    >
                        #{review.pr_number ?? review.head_branch}
                    </Link>
                    {hasCompletedTurn(review) ? (
                        // A real button, so keyboard users can open the findings the row click opens.
                        <Link
                            subtle
                            className="block max-w-80 truncate text-left font-semibold"
                            title={reviewTitle(review)}
                            onClick={(event) => {
                                event.stopPropagation()
                                openReviewDetail(review)
                            }}
                        >
                            {reviewTitle(review)}
                        </Link>
                    ) : (
                        <span className="block max-w-80 truncate font-semibold" title={reviewTitle(review)}>
                            {reviewTitle(review)}
                        </span>
                    )}
                </div>
            ),
        },
        {
            title: 'Repository',
            dataIndex: 'repository',
            render: (_, review) => <span className="whitespace-nowrap font-mono text-xs">{review.repository}</span>,
        },
        ...(reviewsScope === ReviewHogReviewsListScope.Everyone
            ? [
                  {
                      title: 'Author',
                      key: 'author',
                      render: (_: unknown, review: ReviewRecentReviewApi) => (
                          <span className="whitespace-nowrap font-mono text-xs">{review.pr_author}</span>
                      ),
                  },
              ]
            : []),
        {
            title: 'Mode',
            key: 'mode',
            render: (_, review) => <ReviewModeTag mode={review.review_mode} />,
        },
        {
            title: 'Findings',
            key: 'findings',
            render: (_, review) => (hasCompletedTurn(review) ? <FindingCounts review={review} /> : null),
        },
        {
            title: 'Posted',
            key: 'posted',
            render: (_, review) =>
                !hasCompletedTurn(review) ? null : review.turn_published ? (
                    <LemonTag type="success" size="small">
                        Posted
                    </LemonTag>
                ) : (
                    <span className="whitespace-nowrap text-xs text-secondary">Not posted</span>
                ),
        },
        {
            title: 'Last activity',
            key: 'last_activity',
            render: (_, review) =>
                review.in_progress ? (
                    <span className="text-xs text-secondary">Now</span>
                ) : review.last_run_at ? (
                    <TZLabel time={review.last_run_at} className="whitespace-nowrap text-xs" />
                ) : null,
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={reviewsPage?.results ?? []}
            loading={!reviewsPage}
            loadingSkeletonRows={5}
            rowKey="id"
            onRow={(review) =>
                hasCompletedTurn(review) ? { onClick: () => openReviewDetail(review), className: 'cursor-pointer' } : {}
            }
            pagination={{
                controlled: true,
                pageSize: REVIEWS_PAGE_SIZE,
                currentPage: reviewsCurrentPage,
                entryCount: reviewsPage?.count ?? 0,
                // The pager enables Next whenever a handler exists, even when nothing matched.
                onForward:
                    reviewsPage && reviewsCurrentPage * REVIEWS_PAGE_SIZE < reviewsPage.count
                        ? () => setReviewsPage(reviewsCurrentPage + 1)
                        : undefined,
                onBackward: reviewsCurrentPage > 1 ? () => setReviewsPage(reviewsCurrentPage - 1) : undefined,
                // The logic keeps `reviews_page` in the URL; the table's own `page` param would overwrite it.
                useUrl: false,
            }}
            nouns={['review', 'reviews']}
            emptyState={<ReviewsEmptyState />}
            data-attr="code-review-reviews-table"
        />
    )
}
