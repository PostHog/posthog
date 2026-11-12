import './QuillInboxList.scss'

import { useActions, useValues } from 'kea'
import { ReactNode, Ref } from 'react'

import { Button, Skeleton, Text } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { userLogic } from 'scenes/userLogic'

import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT } from '../../types'
import type { MergedReportRow } from '../../utils/flatReportList'
import { isForYouReport } from '../../utils/reportFacts'
import { QuillReportRow } from '../cards/QuillReportRow'
import { QuillInboxFilterChips } from '../shell/QuillInboxFilterChips'

export type QuillReportsListState = 'empty-inbox' | 'loading' | 'failed' | 'no-match' | 'rows'

function Group({
    title,
    count,
    rows,
    timestampField,
}: {
    title: string
    count: number
    rows: MergedReportRow[]
    timestampField: 'created_at' | 'updated_at'
}): JSX.Element | null {
    if (rows.length === 0) {
        return null
    }
    return (
        <section className="flex flex-col" aria-label={title}>
            <h2 className="QuillInboxGroup__heading">
                <span>{title}</span>
                <span className="QuillInboxGroup__count" translate="no">
                    {count}
                </span>
            </h2>
            <ol className="QuillReportRows">
                {rows.map(({ report, sectionKey }) => (
                    <QuillReportRow
                        key={report.id}
                        report={report}
                        sectionKey={sectionKey}
                        timestampField={timestampField}
                    />
                ))}
            </ol>
        </section>
    )
}

function RowsSkeleton({ count }: { count: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-5 py-2" aria-busy aria-label="Loading reports">
            {Array.from({ length: count }, (_, index) => (
                <div key={index} className="flex items-start gap-3">
                    <Skeleton className="size-5.5 rounded-md" />
                    <div className="flex flex-1 flex-col gap-2">
                        <Skeleton className="h-4 w-3/5" />
                        <Skeleton className="h-3 w-2/5" />
                    </div>
                </div>
            ))}
        </div>
    )
}

/** The Quill view of the Reports tab. `ReportsTab` owns the data and the paging, and this only draws them. */
export function QuillReportsList({
    state,
    rows,
    totalCount,
    timestampField,
    emptyCopy,
    emptyInbox,
    banners,
    pageLoading,
    someLoadFailed,
    pageLoadFailed,
    hasMore,
    sentinelRef,
    onRetry,
    onRetryPage,
}: {
    state: QuillReportsListState
    rows: MergedReportRow[]
    /** How many reports the selected states hold on the server, loaded or not. */
    totalCount: number
    timestampField: 'created_at' | 'updated_at'
    emptyCopy: string
    emptyInbox: ReactNode
    banners: ReactNode
    pageLoading: boolean
    someLoadFailed: boolean
    pageLoadFailed: boolean
    hasMore: boolean
    sentinelRef: Ref<HTMLDivElement>
    onRetry: () => void
    onRetryPage: () => void
}): JSX.Element {
    const { user } = useValues(userLogic)
    const { scope, hasActiveFilters } = useValues(inboxFiltersLogic)
    const { clearFilters } = useActions(inboxFiltersLogic)
    const myUuid = user?.uuid ?? null
    // The "For you" group needs the whole project in the list. In a narrower scope every row is one group.
    const grouped = scope === INBOX_SCOPE_ENTIRE_PROJECT && !hasActiveFilters
    const forYou = grouped ? rows.filter(({ report }) => isForYouReport(report, myUuid)) : []
    const others = grouped ? rows.filter(({ report }) => !isForYouReport(report, myUuid)) : rows
    const count = Math.max(totalCount, rows.length)

    return (
        <div className="Today">
            <div className="QuillInbox QuillInbox--body Today__page flex flex-col gap-6" data-quill>
                <QuillInboxFilterChips />
                {banners}
                {state === 'empty-inbox' && emptyInbox}
                {state === 'loading' && <RowsSkeleton count={4} />}
                {state === 'failed' && (
                    <div className="flex flex-col items-start gap-2 py-6">
                        <Text size="sm" variant="muted" render={<p className="m-0" />}>
                            Couldn't load these reports.
                        </Text>
                        <Button
                            variant="outline"
                            loading={pageLoading}
                            onClick={onRetry}
                            data-attr="inbox-report-list-retry"
                        >
                            Retry
                        </Button>
                    </div>
                )}
                {state === 'no-match' && (
                    <div className="flex flex-col items-start gap-1.5 py-7" data-attr="inbox-report-list-empty">
                        <Text size="base" weight="medium" render={<p className="m-0" />}>
                            {hasActiveFilters ? 'No reports match these filters' : emptyCopy}
                        </Text>
                        {hasActiveFilters && (
                            <Button
                                variant="outline"
                                className="mt-2.5"
                                onClick={() => clearFilters()}
                                data-attr="inbox-report-list-clear-filters"
                            >
                                Clear filters
                            </Button>
                        )}
                    </div>
                )}
                {state === 'rows' && (
                    <div className="flex flex-col gap-7">
                        <Group title="For you" count={forYou.length} rows={forYou} timestampField={timestampField} />
                        <Group
                            title={forYou.length > 0 ? 'All other reports' : 'Reports'}
                            count={count - forYou.length}
                            rows={others}
                            timestampField={timestampField}
                        />
                        {pageLoading && <RowsSkeleton count={2} />}
                        {someLoadFailed && (
                            <div className="flex items-center gap-2">
                                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                                    Couldn't load some of the reports.
                                </Text>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    loading={pageLoading}
                                    onClick={onRetry}
                                    data-attr="inbox-report-list-retry"
                                >
                                    Retry
                                </Button>
                            </div>
                        )}
                        {!pageLoading && pageLoadFailed && (
                            <div className="flex items-center gap-2">
                                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                                    Couldn't load more reports.
                                </Text>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={onRetryPage}
                                    data-attr="inbox-report-list-retry-page"
                                >
                                    Retry
                                </Button>
                            </div>
                        )}
                        {hasMore && <div ref={sentinelRef} className="h-1" aria-hidden />}
                    </div>
                )}
            </div>
        </div>
    )
}
