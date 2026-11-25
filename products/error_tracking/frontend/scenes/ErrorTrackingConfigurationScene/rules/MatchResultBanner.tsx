import { ReactNode } from 'react'

import { LemonButton, Link } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { matchingExceptionsUrl, matchingIssuesUrl } from './ruleMatchUrls'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const dateRangeLabel = DATE_RANGE_LABELS[dateRange] ?? '7 days'
    const nextRange = NEXT_DATE_RANGE[dateRange]

    if (matchResult.exceptionCount === 0) {
        return (
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span>No exceptions matched in the last {dateRangeLabel}</span>
                {nextRange &&
                    onIncreaseDateRange &&
                    (todayRailNav ? (
                        <Button variant="outline" size="sm" onClick={onIncreaseDateRange}>
                            Try last {DATE_RANGE_LABELS[nextRange]}
                        </Button>
                    ) : (
                        <LemonButton type="secondary" size="xsmall" onClick={onIncreaseDateRange}>
                            Try last {DATE_RANGE_LABELS[nextRange]}
                        </LemonButton>
                    ))}
            </div>
        )
    }

    const issuesUrl = matchingIssuesUrl(properties, filterType, dateRange)
    const exceptionsUrl = matchingExceptionsUrl(properties, dateRange)

    const resultLink = (to: string, children: ReactNode): JSX.Element =>
        todayRailNav ? (
            <Button
                variant="link"
                size="inline"
                nativeButton={false}
                render={<LinkPrimitive to={`${window.location.origin}${to}`} target="_blank" />}
            >
                {children}
            </Button>
        ) : (
            <Link to={`${window.location.origin}${to}`} target="_blank" targetBlankIcon={false}>
                {children}
            </Link>
        )

    const issuesLink = resultLink(
        issuesUrl,
        <>
            {matchResult.issueCount.toLocaleString()} issue
            {matchResult.issueCount === 1 ? '' : 's'}
        </>
    )

    const hasSampling = samplingRate !== undefined && samplingRate < 1

    return (
        <span>
            {hasSampling ? (
                <>
                    ~{Math.round(matchResult.exceptionCount * samplingRate).toLocaleString()} of{' '}
                    {resultLink(
                        exceptionsUrl,
                        <>
                            {matchResult.exceptionCount.toLocaleString()} matching exception
                            {matchResult.exceptionCount === 1 ? '' : 's'}
                        </>
                    )}
                </>
            ) : (
                resultLink(
                    exceptionsUrl,
                    <>
                        {matchResult.exceptionCount.toLocaleString()} exception
                        {matchResult.exceptionCount === 1 ? '' : 's'}
                    </>
                )
            )}{' '}
            {suffix(issuesLink, dateRangeLabel)}
        </span>
    )
}
