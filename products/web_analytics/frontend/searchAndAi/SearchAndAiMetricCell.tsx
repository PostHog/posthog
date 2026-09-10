import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconTrending } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import {
    changeVsPrevious,
    formatShare,
    PagePerformanceMetric,
    pagePerformanceLogic,
    parseMetricCell,
} from 'scenes/web-analytics/pagePerformanceLogic'

export type SearchAndAiMetric =
    | 'visitors'
    | 'google_search'
    | 'llm_referrals'
    | 'agent_crawls'
    | 'conversions'
    | 'avg_time'

const METRIC_INDEX: Record<SearchAndAiMetric, number> = {
    visitors: 1,
    google_search: 2,
    llm_referrals: 3,
    agent_crawls: 4,
    conversions: 5,
    avg_time: 6,
}

const isBreakdownMetric = (metric: SearchAndAiMetric): metric is PagePerformanceMetric =>
    metric === 'google_search' || metric === 'llm_referrals' || metric === 'agent_crawls'

export function SearchAndAiMetricCell({ metric, record }: { metric: SearchAndAiMetric; record: unknown }): JSX.Element {
    const { comparePeriods, siteVisitors, conversionGoal, dataState } = useValues(pagePerformanceLogic)
    const { openBreakdown } = useActions(pagePerformanceLogic)
    const row = Array.isArray(record) ? record : []
    const value = row[METRIC_INDEX[metric]]
    const cell = parseMetricCell(value)
    const current = cell?.current ?? 0
    const previous = cell?.previous ?? 0
    const visitors = parseMetricCell(row[1])?.current ?? 0
    const share = formatShare(current, metric === 'visitors' ? siteVisitors : visitors)
    const isCrawler = metric === 'agent_crawls'

    if (metric === 'avg_time') {
        return (
            <Tooltip title="The 90th percentile time visitors spent on this page before moving on. A following pageview is needed, so the last page of a visit is not counted.">
                <span>{value ? humanFriendlyDuration(Number(value)) : 'No timing yet'}</span>
            </Tooltip>
        )
    }
    if (metric === 'conversions' && !conversionGoal) {
        return (
            <Tooltip title="Choose a conversion goal to see conversions for each page.">
                <span className="text-secondary">Not set</span>
            </Tooltip>
        )
    }
    if (isCrawler && dataState.crawlers === 'needs-server-logs') {
        return (
            <Tooltip title="Forward your server access logs to measure AI crawlers. Crawlers do not run the browser SDK.">
                <span className="text-secondary">Not measured</span>
            </Tooltip>
        )
    }

    const change = comparePeriods && !isCrawler ? changeVsPrevious(current, previous) : null
    const TrendIcon = change === 0 ? IconTrendingFlat : (change ?? 0) > 0 ? IconTrending : IconTrendingDown

    const tooltip = {
        visitors: `${share ?? '0%'} of the ${siteVisitors.toLocaleString()} visitors to your site this period`,
        google_search: `${current.toLocaleString()} of this page's ${visitors.toLocaleString()} visitors came from Google search`,
        llm_referrals: `${current.toLocaleString()} of this page's ${visitors.toLocaleString()} visitors arrived from an AI assistant. This is a lower bound: some assistants strip the referrer, so those visits land in Direct`,
        agent_crawls: `${current.toLocaleString()} crawls by ${pluralize(previous, 'agent')}. Crawls count every bot hit, not unique visitors`,
        conversions: `${current.toLocaleString()} conversions from this page's ${visitors.toLocaleString()} visitors`,
    }[metric]
    const content = (
        <span className="flex flex-col items-center leading-tight tabular-nums">
            <span className="whitespace-nowrap">{current.toLocaleString()}</span>
            <span className="inline-flex items-center gap-1 text-xs text-secondary whitespace-nowrap">
                {isCrawler ? <span>{current > 0 ? pluralize(previous, 'agent') : null}</span> : <span>{share}</span>}
                {change !== null && (
                    <span
                        className={clsx(
                            'inline-flex items-center',
                            change === 0 ? 'text-secondary' : change > 0 ? 'text-success' : 'text-danger'
                        )}
                    >
                        <TrendIcon />
                        <span>{percentage(Math.abs(change), 0)}</span>
                    </span>
                )}
            </span>
        </span>
    )
    const title = [
        tooltip,
        change === null
            ? null
            : `${change > 0 ? 'Increased' : change < 0 ? 'Decreased' : 'Changed'} by ${percentage(Math.abs(change), 0)} vs previous period`,
    ]
        .filter(Boolean)
        .join('. ')

    return (
        <Tooltip title={title}>
            {isBreakdownMetric(metric) ? (
                <LemonButton
                    type="tertiary"
                    size="small"
                    noPadding
                    fullWidth
                    center
                    className="hover:underline"
                    onClick={() => openBreakdown({ page: String(row[0] ?? ''), metric })}
                    data-attr={`page-performance-breakdown-${metric}`}
                >
                    {content}
                </LemonButton>
            ) : (
                <span className="inline-block">{content}</span>
            )}
        </Tooltip>
    )
}
