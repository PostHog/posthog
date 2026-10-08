import { useActions, useValues } from 'kea'

import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { tryDecodeURIComponent } from 'lib/utils/url'
import { TileId } from 'scenes/web-analytics/common'
import { createPagePerformanceInsightProps, pagePerformanceLogic } from 'scenes/web-analytics/pagePerformanceLogic'

import { QueryContext, QueryContextColumnTitleComponent } from '~/queries/types'

import { SearchAndAiMetric, SearchAndAiMetricCell } from './SearchAndAiMetricCell'
import { SearchAndAiQuery } from './SearchAndAiQuery'

const METRIC_COLUMNS: { value: SearchAndAiMetric; label: string }[] = [
    { value: 'visitors', label: 'Visitors' },
    { value: 'google_search', label: 'Google search' },
    { value: 'llm_referrals', label: 'AI referrals' },
    { value: 'agent_crawls', label: 'AI crawls' },
    { value: 'conversions', label: 'Conversions' },
    { value: 'avg_time', label: 'Time on page (P90)' },
]

const sortableTitle = (label: string, column: string): QueryContextColumnTitleComponent =>
    function SortableTitle(): JSX.Element {
        const { orderBy } = useValues(pagePerformanceLogic)
        const { setOrderBy } = useActions(pagePerformanceLogic)
        const active = orderBy.column === column
        return (
            <LemonButton
                type="tertiary"
                size="small"
                noPadding
                fullWidth
                center
                onClick={() => setOrderBy(column, active && orderBy.direction === 'DESC' ? 'ASC' : 'DESC')}
                aria-label={`Sort by ${label} ${active && orderBy.direction === 'DESC' ? 'ascending' : 'descending'}`}
            >
                <span className="whitespace-normal">{label}</span>
                {active && (orderBy.direction === 'ASC' ? <IconArrowUp /> : <IconArrowDown />)}
            </LemonButton>
        )
    }

const insightProps = createPagePerformanceInsightProps(TileId.PAGE_PERFORMANCE_TABLE, 'table')
const context: QueryContext = {
    insightProps,
    tableLayout: 'fixed',
    columns: {
        breakdown_value: {
            title: 'Page',
            width: '28%',
            render: ({ value }) => {
                const page = typeof value === 'string' ? tryDecodeURIComponent(value) : '(none)'
                return (
                    <Tooltip title={page}>
                        <span className="block truncate font-medium">{page}</span>
                    </Tooltip>
                )
            },
        },
        ...Object.fromEntries(
            METRIC_COLUMNS.map(({ value, label }) => [
                value,
                {
                    renderTitle: sortableTitle(label, value),
                    render: ({ record }: { record: unknown }) => (
                        <SearchAndAiMetricCell metric={value} record={record} />
                    ),
                    align: 'center',
                },
            ])
        ),
    },
}

export function SearchAndAiTable(): JSX.Element {
    const { pageTableQuery, pageTableInput, candidatesLoading, footerText } = useValues(pagePerformanceLogic)

    return (
        <div className="min-w-0">
            <SearchAndAiQuery
                uniqueKey="page-performance-table"
                pending={candidatesLoading}
                resultsKey={pageTableInput}
                query={pageTableQuery}
                insightProps={insightProps}
                context={context}
                footer={footerText}
                dataAttr="page-performance-table"
            />
        </div>
    )
}
