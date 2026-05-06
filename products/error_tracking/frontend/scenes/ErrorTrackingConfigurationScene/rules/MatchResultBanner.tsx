import { combineUrl } from 'kea-router'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab, AnyPropertyFilter, FilterLogicalOperator } from '~/types'

const DATE_RANGE_LABELS: Record<string, string> = {
    '-7d': '7 days',
    '-30d': '30 days',
    '-90d': '90 days',
}

const NEXT_DATE_RANGE: Record<string, string> = {
    '-7d': '-30d',
    '-30d': '-90d',
}

export function MatchResultBanner({
    matchResult,
    properties,
    filterType = FilterLogicalOperator.And,
    suffix,
    dateRange = '-7d',
    onIncreaseDateRange,
    samplingRate,
}: {
    matchResult: { exceptionCount: number; issueCount: number }
    properties: AnyPropertyFilter[]
    filterType?: FilterLogicalOperator
    suffix: (issuesLink: JSX.Element, dateRangeLabel: string) => JSX.Element
    dateRange?: string
    onIncreaseDateRange?: () => void
    samplingRate?: number
}): JSX.Element {
    const dateRangeLabel = DATE_RANGE_LABELS[dateRange] ?? '7 days'
    const nextRange = NEXT_DATE_RANGE[dateRange]

    if (matchResult.exceptionCount === 0) {
        return (
            <div className="flex items-center justify-between gap-2">
                <span>No exceptions matched in the last {dateRangeLabel}</span>
                {nextRange && onIncreaseDateRange && (
                    <LemonButton type="secondary" size="xsmall" onClick={onIncreaseDateRange}>
                        Try last {DATE_RANGE_LABELS[nextRange]}
                    </LemonButton>
                )}
            </div>
        )
    }

    const issuesUrl = urls.errorTracking({
        filterGroup: { type: filterType, values: [{ type: filterType, values: properties }] },
        dateRange: { date_from: dateRange, date_to: null },
    })

    const exceptionsUrl = combineUrl(
        urls.activity(ActivityTab.ExploreEvents),
        {},
        {
            q: {
                kind: NodeKind.DataTableNode,
                full: true,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: defaultDataTableColumns(NodeKind.EventsQuery),
                    orderBy: ['timestamp DESC'],
                    after: dateRange,
                    event: '$exception',
                    properties,
                    tags: { productKey: ProductKey.ERROR_TRACKING },
                },
                propertiesViaUrl: true,
                showPersistentColumnConfigurator: true,
            },
        }
    ).url

    const issuesLink = (
        <Link to={`${window.location.origin}${issuesUrl}`} target="_blank" targetBlankIcon={false}>
            {matchResult.issueCount.toLocaleString()} issue
            {matchResult.issueCount === 1 ? '' : 's'}
        </Link>
    )

    const hasSampling = samplingRate !== undefined && samplingRate < 1

    return (
        <span>
            {hasSampling ? (
                <>
                    ~{Math.round(matchResult.exceptionCount * samplingRate).toLocaleString()} of{' '}
                    <Link to={`${window.location.origin}${exceptionsUrl}`} target="_blank" targetBlankIcon={false}>
                        {matchResult.exceptionCount.toLocaleString()} matching exception
                        {matchResult.exceptionCount === 1 ? '' : 's'}
                    </Link>
                </>
            ) : (
                <Link to={`${window.location.origin}${exceptionsUrl}`} target="_blank" targetBlankIcon={false}>
                    {matchResult.exceptionCount.toLocaleString()} exception
                    {matchResult.exceptionCount === 1 ? '' : 's'}
                </Link>
            )}{' '}
            {suffix(issuesLink, dateRangeLabel)}
        </span>
    )
}
