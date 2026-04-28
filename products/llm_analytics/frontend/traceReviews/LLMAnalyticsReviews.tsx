import { useActions, useMountedLogic, useValues } from 'kea'

import { IconDownload } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonMenu,
    LemonSelect,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
} from '@posthog/lemon-ui'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { updatedAtColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { urls } from '~/scenes/urls'
import { ExporterFormat } from '~/types'

import { llmAnalyticsReviewsLogic, TRACE_REVIEWS_PER_PAGE } from './llmAnalyticsReviewsLogic'
import { buildTraceReviewsListUrl } from './traceReviewsApi'
import { copyReviewsAs } from './traceReviewsExport'
import { TraceReviewValue } from './TraceReviewValue'
import type { TraceReview } from './types'

function formatTraceId(traceId: string): string {
    return traceId.length > 12 ? `${traceId.slice(0, 4)}...${traceId.slice(-4)}` : traceId
}

export function LLMAnalyticsReviews({ tabId }: { tabId?: string }): JSX.Element {
    const logic = useMountedLogic(llmAnalyticsReviewsLogic({ tabId }))
    const { setFilters } = useActions(logic)
    const { startExport } = useActions(exportsLogic)
    const {
        reviews,
        reviewsLoading,
        sorting,
        pagination,
        filters,
        reviewCountLabel,
        scoreDefinitionOptions,
        scoreDefinitionOptionsLoading,
    } = useValues(logic)

    const exportPath = buildTraceReviewsListUrl(undefined, {
        search: filters.search || undefined,
        definition_id: filters.definition_id || undefined,
        order_by: filters.order_by,
    })

    const triggerFileExport = (format: ExporterFormat, extension: 'csv' | 'xlsx'): void => {
        startExport({
            export_format: format,
            export_context: {
                path: exportPath,
                method: 'GET',
                filename: `trace_reviews.${extension}`,
            },
        })
    }

    const hasLoadedReviews = reviews.results.length > 0
    const exportDisabledReason = !hasLoadedReviews
        ? reviewsLoading
            ? 'Loading reviews...'
            : 'No reviews to export'
        : undefined

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
                        <Link to={urls.llmAnalyticsTrace(value)} data-attr="llma-trace-review-trace-link">
                            {formatTraceId(value)}
                        </Link>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Review',
            key: 'review',
            width: '16%',
            render: function renderReview(_, review) {
                return <TraceReviewValue review={review} />
            },
        },
        {
            title: 'Comment',
            dataIndex: 'comment',
            key: 'comment',
            width: '34%',
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
                <div className="flex gap-2 items-center flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Search reviews..."
                        value={filters.search}
                        onChange={(value) => setFilters({ search: value })}
                        className="max-w-md"
                        data-attr="llma-trace-reviews-search-input"
                    />
                    <LemonSelect
                        value={filters.definition_id || undefined}
                        onChange={(value) => setFilters({ definition_id: value ? String(value) : '' })}
                        options={[
                            { label: 'All scorers', value: '' },
                            ...scoreDefinitionOptions.map((definition) => ({
                                label: definition.name,
                                value: definition.id,
                            })),
                        ]}
                        placeholder="Filter by scorer"
                        loading={scoreDefinitionOptionsLoading}
                        className="min-w-60"
                        data-attr="llma-trace-reviews-definition-filter"
                    />
                </div>
                <div className="flex gap-2 items-center">
                    <span className="text-muted-alt">{reviewCountLabel}</span>
                    <LemonMenu
                        items={[
                            {
                                label: 'Export current columns',
                                items: [
                                    {
                                        label: 'CSV',
                                        onClick: () => triggerFileExport(ExporterFormat.CSV, 'csv'),
                                    },
                                    {
                                        label: 'XLSX',
                                        onClick: () => triggerFileExport(ExporterFormat.XLSX, 'xlsx'),
                                    },
                                ],
                            },
                            {
                                label: 'Copy to clipboard',
                                items: [
                                    {
                                        label: 'CSV',
                                        onClick: () => void copyReviewsAs(reviews.results, 'csv'),
                                        'data-attr': 'copy-csv-to-clipboard',
                                    },
                                    {
                                        label: 'JSON',
                                        onClick: () => void copyReviewsAs(reviews.results, 'json'),
                                        'data-attr': 'copy-json-to-clipboard',
                                    },
                                    {
                                        label: 'Excel',
                                        onClick: () => void copyReviewsAs(reviews.results, 'tsv'),
                                        'data-attr': 'copy-excel-to-clipboard',
                                    },
                                ],
                            },
                        ]}
                    >
                        <LemonButton
                            type="secondary"
                            icon={<IconDownload />}
                            size="small"
                            disabledReason={exportDisabledReason}
                            data-attr="llma-trace-reviews-export-menu"
                        >
                            Export
                        </LemonButton>
                    </LemonMenu>
                </div>
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
