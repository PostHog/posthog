import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import useResizeObserver from 'use-resize-observer'

import { IconWarning } from '@posthog/icons'
import { LemonSkeleton, LemonTable, LemonTableColumns, Link, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils/durations'
import { tryDecodeURIComponent } from 'lib/utils/url'
import { pageReportsLogic } from 'scenes/web-analytics/pageReportsLogic'

import { WebPageDirectoryMetric, WebPageDirectoryRow, WebPageDirectorySortBy } from '~/queries/schema/schema-general'

import { CrawlerLogoStack } from './CrawlerLogoStack'
import { PageDirectoryEmptyState } from './PageDirectoryEmptyState'
import { PAGE_DIRECTORY_PAGE_SIZE, pageDirectoryLogic } from './pageDirectoryLogic'
import { PageDirectoryMetricCell } from './PageDirectoryMetricCell'
import { pageReportPath, pageReportUrlForPage, splitPageKey } from './pageReportsUtils'

const NARROW_WIDTH = 560
const COMPACT_WIDTH = 900
const MEDIUM_WIDTH = 1200

export function PageDirectoryTable(): JSX.Element {
    const {
        rows,
        driverLoading,
        hasMore,
        pageIndex,
        sortBy,
        sortDirection,
        visibleMetrics,
        metricLoading,
        hasServerLogs,
        singleHost,
    } = useValues(pageDirectoryLogic)
    const { setSort, nextPage, previousPage } = useActions(pageDirectoryLogic)
    const { searchParams } = useValues(router)
    const { openPageReport } = useActions(pageReportsLogic)
    const { ref, width = 0 } = useResizeObserver<HTMLDivElement>()

    const sortColumnKey: string = sortBy
    const isNarrow = width > 0 && width < NARROW_WIDTH
    const isCompact = width > 0 && width < COMPACT_WIDTH
    const isMedium = width > 0 && width < MEDIUM_WIDTH
    const hiddenOnNarrow = (key: string): boolean =>
        key !== sortColumnKey &&
        ((isNarrow && key !== WebPageDirectoryMetric.Visitors) ||
            (isCompact && key === WebPageDirectoryMetric.AiCrawls) ||
            (isMedium && (key === WebPageDirectoryMetric.TimeOnPage || key === WebPageDirectoryMetric.Conversions)))
    const isLoading = (metric: WebPageDirectoryMetric): boolean => driverLoading || !!metricLoading[metric]

    const columns: LemonTableColumns<WebPageDirectoryRow> = [
        {
            key: 'page',
            title: 'Page',
            sorter: true,
            render: (_, row, index) => {
                const { host, path } = splitPageKey(tryDecodeURIComponent(row.page))
                return (
                    <Tooltip title={pageReportUrlForPage(row.page)}>
                        <Link
                            to={pageReportPath(row.page, searchParams)}
                            subtle
                            className="flex flex-col min-w-0 max-w-80 py-0.5"
                            onClick={(event) => {
                                event.stopPropagation()
                                if (!event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) {
                                    event.preventDefault()
                                    openPageReport(pageReportUrlForPage(row.page), 'directory_row', index)
                                }
                            }}
                            data-attr="page-reports-directory-row"
                        >
                            <span className="truncate font-semibold text-primary">{path}</span>
                            {host && !singleHost ? (
                                <span className="truncate text-xs text-secondary">{host}</span>
                            ) : null}
                        </Link>
                    </Tooltip>
                )
            },
        },
        {
            key: WebPageDirectoryMetric.Visitors,
            title: 'Visitors',
            align: 'right',
            sorter: true,
            isHidden: hiddenOnNarrow(WebPageDirectoryMetric.Visitors),
            render: (_, row) => (
                <PageDirectoryMetricCell
                    value={row.visitors}
                    tooltip="People who viewed this page"
                    loading={isLoading(WebPageDirectoryMetric.Visitors)}
                />
            ),
        },
        {
            key: WebPageDirectoryMetric.GoogleSearch,
            title: 'Google search',
            tooltip: 'Visitors whose session started from a Google search result',
            align: 'right',
            sorter: true,
            isHidden: hiddenOnNarrow(WebPageDirectoryMetric.GoogleSearch),
            render: (_, row) => (
                <PageDirectoryMetricCell
                    value={row.googleSearch}
                    tooltip="Visitors to this page who came from Google search"
                    loading={isLoading(WebPageDirectoryMetric.GoogleSearch)}
                />
            ),
        },
        {
            key: WebPageDirectoryMetric.AiReferrals,
            title: 'AI referrals',
            tooltip: 'Visitors whose session started from an AI assistant such as ChatGPT, Claude or Perplexity',
            align: 'right',
            sorter: true,
            isHidden: hiddenOnNarrow(WebPageDirectoryMetric.AiReferrals),
            render: (_, row) => (
                <PageDirectoryMetricCell
                    value={row.aiReferrals}
                    tooltip="Visitors to this page who came from an AI assistant"
                    loading={isLoading(WebPageDirectoryMetric.AiReferrals)}
                />
            ),
        },
        {
            key: WebPageDirectoryMetric.AiCrawls,
            title: 'AI crawls',
            tooltip: 'Requests from AI crawlers. Crawlers are not counted as visitors.',
            align: 'right',
            sorter: true,
            isHidden: hiddenOnNarrow(WebPageDirectoryMetric.AiCrawls),
            render: (_, row) =>
                hasServerLogs === false ? (
                    <Tooltip title="Forward your server logs to measure AI crawlers. Crawlers do not run the browser SDK.">
                        <span className="text-secondary">Not measured</span>
                    </Tooltip>
                ) : (
                    <PageDirectoryMetricCell
                        value={row.aiCrawls}
                        detail={
                            row.aiCrawls?.current ? (
                                <CrawlerLogoStack names={row.aiCrawlerNames ?? []} count={row.aiCrawlers ?? 0} />
                            ) : null
                        }
                        tooltip="Requests from AI crawlers in this period"
                        loading={isLoading(WebPageDirectoryMetric.AiCrawls)}
                    />
                ),
        },
        {
            key: WebPageDirectoryMetric.Conversions,
            title: 'Conversions',
            align: 'right',
            sorter: true,
            isHidden:
                !visibleMetrics.includes(WebPageDirectoryMetric.Conversions) ||
                hiddenOnNarrow(WebPageDirectoryMetric.Conversions),
            render: (_, row) => (
                <PageDirectoryMetricCell
                    value={row.conversions}
                    tooltip="Conversion goal events that happened on this page"
                    loading={isLoading(WebPageDirectoryMetric.Conversions)}
                />
            ),
        },
        {
            key: WebPageDirectoryMetric.TimeOnPage,
            title: 'Time on page',
            tooltip:
                'The time 90% of visitors spent on this page or less. A following pageview is needed, so the last page of a visit is not counted.',
            align: 'right',
            sorter: true,
            isHidden: hiddenOnNarrow(WebPageDirectoryMetric.TimeOnPage),
            render: (_, row) =>
                row.timeOnPageP90 != null ? (
                    row.timeOnPageP90 < 1 ? (
                        <Tooltip title="Most visits end in under a second, which usually means this page redirects.">
                            <span className="inline-flex items-center gap-1 text-warning tabular-nums" translate="no">
                                <IconWarning />
                                Under 1s
                            </span>
                        </Tooltip>
                    ) : (
                        <span className="tabular-nums" translate="no">
                            {humanFriendlyDuration(row.timeOnPageP90)}
                        </span>
                    )
                ) : isLoading(WebPageDirectoryMetric.TimeOnPage) ? (
                    <LemonSkeleton className="h-4 w-12 ml-auto" />
                ) : (
                    <span className="text-secondary">-</span>
                ),
        },
    ]

    return (
        <div ref={ref} className="min-w-0">
            <LemonTable<WebPageDirectoryRow>
                dataSource={rows}
                columns={columns}
                rowKey="page"
                loading={driverLoading}
                loadingSkeletonRows={10}
                useURLForSorting={false}
                noSortingCancellation
                sorting={{ columnKey: sortColumnKey, order: sortDirection === 'ASC' ? 1 : -1 }}
                onSort={(sorting) => {
                    if (!sorting) {
                        return
                    }
                    const column = sorting.columnKey as WebPageDirectorySortBy
                    if (column !== sortBy) {
                        setSort(column, column === WebPageDirectorySortBy.Page ? 'ASC' : 'DESC')
                        return
                    }
                    setSort(column, sortDirection === 'DESC' ? 'ASC' : 'DESC')
                }}
                onRow={(row, index) => ({
                    className: 'cursor-pointer',
                    onClick: () => openPageReport(pageReportUrlForPage(row.page), 'directory_row', index),
                })}
                pagination={{
                    controlled: true,
                    pageSize: PAGE_DIRECTORY_PAGE_SIZE,
                    currentPage: pageIndex + 1,
                    onForward: hasMore ? nextPage : undefined,
                    onBackward: pageIndex > 0 ? previousPage : undefined,
                }}
                nouns={['row', 'rows']}
                emptyState={<PageDirectoryEmptyState />}
                data-attr="page-reports-directory-table"
            />
        </div>
    )
}
