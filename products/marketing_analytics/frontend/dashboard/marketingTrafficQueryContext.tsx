import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { webAnalyticsDataTableQueryContext } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { WebAnalyticsOrderByDirection, WebAnalyticsOrderByFields } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnTitleComponent } from '~/queries/types'

export function marketingTrafficQueryContext(
    orderBy: [WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection] | undefined,
    onSort: (field: WebAnalyticsOrderByFields) => void
): QueryContext {
    const sortableTitle = (label: string, field: WebAnalyticsOrderByFields): QueryContextColumnTitleComponent =>
        function TrafficColumnTitle() {
            const selected = orderBy?.[0] === field
            return (
                <LemonButton
                    size="xsmall"
                    onClick={() => onSort(field)}
                    sideIcon={
                        <IconChevronDown
                            className={selected ? (orderBy?.[1] === 'ASC' ? 'rotate-180' : '') : 'opacity-40'}
                        />
                    }
                    aria-label={`Sort by ${label}${selected ? `, ${orderBy?.[1] === 'ASC' ? 'ascending' : 'descending'}` : ''}`}
                >
                    {label}
                </LemonButton>
            )
        }

    return {
        ...webAnalyticsDataTableQueryContext,
        columns: {
            ...webAnalyticsDataTableQueryContext.columns,
            visitors: {
                ...webAnalyticsDataTableQueryContext.columns?.visitors,
                renderTitle: sortableTitle('Visitors', WebAnalyticsOrderByFields.Visitors),
            },
            sessions: {
                renderTitle: () => <>Sessions</>,
                render: webAnalyticsDataTableQueryContext.columns?.visitors?.render,
                align: 'right',
            },
            views: {
                ...webAnalyticsDataTableQueryContext.columns?.views,
                renderTitle: sortableTitle('Pageviews', WebAnalyticsOrderByFields.Views),
            },
            bounce_rate: {
                ...webAnalyticsDataTableQueryContext.columns?.bounce_rate,
                renderTitle: sortableTitle('Bounce rate', WebAnalyticsOrderByFields.BounceRate),
            },
            unique_conversions: {
                ...webAnalyticsDataTableQueryContext.columns?.unique_conversions,
                renderTitle: sortableTitle('New customers', WebAnalyticsOrderByFields.UniqueConversions),
            },
            conversion_rate: {
                ...webAnalyticsDataTableQueryContext.columns?.conversion_rate,
                renderTitle: sortableTitle('Customer-to-visitor ratio', WebAnalyticsOrderByFields.ConversionRate),
            },
        },
    }
}
