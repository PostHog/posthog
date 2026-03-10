import { useValues, useMountedLogic, useActions } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { LemonInput } from '~/lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { updatedAtColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { urls } from '~/scenes/urls'

import { llmAnalyticsReviewsLogic, TRACE_REVIEWS_PER_PAGE } from './llmAnalyticsReviewsLogic'
import { TraceReviewValue } from './TraceReviewValue'
import type { TraceReview } from './types'

function formatTraceId(traceId: string): string {
    return traceId.length > 12 ? `${traceId.slice(0, 4)}...${traceId.slice(-4)}` : traceId
}

export function LLMAnalyticsReviews({ tabId }: { tabId?: string }): JSX.Element {
    const logic = useMountedLogic(llmAnalyticsReviewsLogic({ tabId }))
    const { setFilters } = useActions(logic)
    const { reviews, reviewsLoading, sorting, pagination, filters, reviewCountLabel } = useValues(logic)

    const columns: LemonTableColumns<TraceReview> = [
        {
            title: 'Trace',
            dataIndex: 'trace_id',
            key: 'trace_id',
            width: '22%',
            render: function renderTraceId(traceId) {
                const value = String(traceId || '')

                if (!value) {
                    return <span className="text-muted">–</span>
                }

                return (
                    <Tooltip title={value}>
                        <Link to={urls.llmAnalyticsTrace(value)} data-attr="trace-review-trace-link">
                            {formatTraceId(value)}
                        </Link>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Review',
            key: 'review',
            width: '14%',
            render: function renderReview(_, review) {
                return <TraceReviewValue review={review} />
            },
        },
        {
            title: 'Comment',
            dataIndex: 'comment',
            key: 'comment',
            width: '38%',
            render: function renderComment(comment) {
                const value = String(comment || '')

                if (!value) {
                    return <span className="text-muted">–</span>
                }

                return (
                    <Tooltip title={value}>
                        <span className="block max-w-2xl truncate text-muted-alt">{value}</span>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Reviewed by',
            dataIndex: 'reviewed_by',
            key: 'reviewed_by',
            render: function renderReviewedBy(_, review) {
                return review.reviewed_by ? (
                    <div className="flex flex-row items-center flex-nowrap">
                        <ProfilePicture user={review.reviewed_by} size="md" showName />
                    </div>
                ) : (
                    <span className="text-muted">–</span>
                )
            },
        },
        updatedAtColumn<TraceReview>() as LemonTableColumn<TraceReview, keyof TraceReview | undefined>,
    ]

    return (
        <div className="space-y-4">
            <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 -mt-4 mb-4 border-b justify-between">
                <LemonInput
                    type="search"
                    placeholder="Search reviews..."
                    value={filters.search}
                    onChange={(value) => setFilters({ search: value })}
                    className="max-w-md"
                    data-attr="trace-reviews-search-input"
                />
                <div className="text-muted-alt">{reviewCountLabel}</div>
            </div>

            <LemonTable
                loading={reviewsLoading}
                columns={columns}
                dataSource={reviews.results}
                pagination={pagination}
                noSortingCancellation
                sorting={sorting}
                onSort={(newSorting) =>
                    setFilters({
                        order_by: newSorting
                            ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                            : undefined,
                    })
                }
                rowKey="id"
                loadingSkeletonRows={TRACE_REVIEWS_PER_PAGE}
                nouns={['review', 'reviews']}
            />
        </div>
    )
}
