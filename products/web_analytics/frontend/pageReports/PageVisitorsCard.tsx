import { WebPageDirectoryValue } from '~/queries/schema/schema-general'

import { formatShare } from 'products/web_analytics/frontend/searchAndAi/searchAndAiQueries'

import { valueChange } from './pageReportsUtils'
import { PageStatCard } from './PageStatCard'
import { TrendChange } from './TrendChange'

export interface PageVisitorsCardProps {
    visitors: WebPageDirectoryValue | null
    siteVisitors: number | null
    onClick: () => void
}

export function PageVisitorsCard({ visitors, siteVisitors, onClick }: PageVisitorsCardProps): JSX.Element {
    const change = valueChange(visitors)
    const share = visitors && siteVisitors ? formatShare(visitors.current, siteVisitors) : null

    return (
        <PageStatCard
            label="Visitors"
            aside={
                change !== null && change !== 0 ? (
                    <TrendChange change={change} className="gap-0.5 text-xs tabular-nums" />
                ) : null
            }
            value={visitors ? visitors.current.toLocaleString() : '-'}
            detail={share ? `${share} of all site visitors` : 'People who viewed this page'}
            loading={!visitors}
            tooltip={
                visitors?.previous != null ? `${visitors.previous.toLocaleString()} in the previous period` : undefined
            }
            onClick={onClick}
            data-attr="page-report-health-card-visitors"
        />
    )
}
