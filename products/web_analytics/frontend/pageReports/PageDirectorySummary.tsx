import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { WebPageDirectoryValue } from '~/queries/schema/schema-general'

import { pageDirectoryLogic } from './pageDirectoryLogic'
import { valueChange } from './pageReportsUtils'
import { TrendChange } from './TrendChange'

function SummaryChange({ value }: { value: WebPageDirectoryValue | undefined }): JSX.Element | null {
    const change = valueChange(value)
    if (change === null) {
        return null
    }
    return (
        <Tooltip title={`${(value?.previous ?? 0).toLocaleString()} in the previous period`}>
            <span>
                <TrendChange change={change} className="gap-0.5 tabular-nums" />
            </span>
        </Tooltip>
    )
}

function SummaryCell({
    label,
    value,
    detail,
    change,
    loading,
}: {
    label: string
    value: string
    detail: string | null
    change?: WebPageDirectoryValue
    loading: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5 px-4 py-3 min-w-0">
            <span className="text-xs font-semibold uppercase tracking-wide text-secondary truncate">{label}</span>
            {loading ? (
                <>
                    <LemonSkeleton className="h-7 w-20" />
                    <LemonSkeleton className="h-3 w-28 mt-1" />
                </>
            ) : (
                <>
                    <span className="flex items-baseline gap-2 min-w-0">
                        <span className="text-xl font-semibold tabular-nums" translate="no">
                            {value}
                        </span>
                        <span className="text-xs">
                            <SummaryChange value={change} />
                        </span>
                    </span>
                    <span className="text-xs text-secondary truncate">{detail}</span>
                </>
            )}
        </div>
    )
}

export function PageDirectorySummary(): JSX.Element {
    const { siteTotals, siteTotalsError, hasServerLogs } = useValues(pageDirectoryLogic)
    const { loadSiteTotals } = useActions(pageDirectoryLogic)
    const loading = !siteTotals

    if (siteTotalsError) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: () => loadSiteTotals(true),
                    'data-attr': 'page-reports-directory-summary-retry',
                }}
            >
                Couldn't load site totals.
            </LemonBanner>
        )
    }
    const visitors = siteTotals?.visitors?.current ?? 0
    const google = siteTotals?.googleSearch?.current ?? 0
    const ai = siteTotals?.aiReferrals?.current ?? 0

    return (
        <div
            className="grid grid-cols-2 @min-[48rem]/main-content:grid-cols-4 border rounded-lg bg-surface-primary divide-x divide-y @min-[48rem]/main-content:divide-y-0"
            data-attr="page-reports-directory-summary"
        >
            <SummaryCell
                label="Visitors"
                value={humanFriendlyLargeNumber(visitors)}
                detail="across all pages"
                change={siteTotals?.visitors}
                loading={loading}
            />
            <SummaryCell
                label="From Google"
                value={humanFriendlyLargeNumber(google)}
                detail="visitors from Google search"
                change={siteTotals?.googleSearch}
                loading={loading}
            />
            <SummaryCell
                label="From AI assistants"
                value={humanFriendlyLargeNumber(ai)}
                detail="visitors from AI assistants"
                change={siteTotals?.aiReferrals}
                loading={loading}
            />
            <SummaryCell
                label="AI crawls"
                value={hasServerLogs === false ? '-' : humanFriendlyLargeNumber(siteTotals?.aiCrawls?.current ?? 0)}
                detail={
                    hasServerLogs === false
                        ? 'Forward server logs to measure'
                        : `by ${pluralize(siteTotals?.aiCrawlers ?? 0, 'AI crawler')}`
                }
                change={hasServerLogs === false ? undefined : siteTotals?.aiCrawls}
                loading={loading}
            />
        </div>
    )
}
