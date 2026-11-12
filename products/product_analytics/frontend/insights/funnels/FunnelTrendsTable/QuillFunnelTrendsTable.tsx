import { useValues } from 'kea'

import { TableCell, TableHead, TableRow } from '@posthog/quill'

import { capitalizeFirstLetter } from 'lib/utils/strings'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { QuillBreakdownValue } from 'products/product_analytics/frontend/insights/shared/InsightsTable/columns/QuillBreakdownValue'
import { QuillDateColumnTitle } from 'products/product_analytics/frontend/insights/shared/QuillDateColumnTitle'
import { QuillDetailedResultsTable } from 'products/product_analytics/frontend/insights/shared/QuillDetailedResultsTable'
import { QuillSeriesSwatch } from 'products/product_analytics/frontend/insights/shared/QuillSeriesSwatch'

import { funnelDataLogic } from '../funnelDataLogic'
import type { FunnelTrendSeries, FunnelTrendsPeriod } from './FunnelTrendsTable'
import { QuillFunnelTrendsValueCell } from './QuillFunnelTrendsValueCell'

interface QuillFunnelTrendsTableProps {
    rows: FunnelTrendSeries[]
    periods: FunnelTrendsPeriod[]
    loading: boolean
    seriesLabel: (row: FunnelTrendSeries) => string
    rowColor: (row: FunnelTrendSeries) => string
    onOpenPersons?: (row: FunnelTrendSeries, periodIndex: number) => void
}

export function QuillFunnelTrendsTable({
    rows,
    periods,
    loading,
    seriesLabel,
    rowColor,
    onOpenPersons,
}: QuillFunnelTrendsTableProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { breakdownFilter, insightData, interval } = useValues(funnelDataLogic(insightProps))
    const { weekStartDay, timezone } = useValues(teamLogic)

    return (
        <QuillDetailedResultsTable
            data-attr="funnel-trends-table"
            loading={loading}
            header={
                <TableRow>
                    <TableHead sticky="left">Series</TableHead>
                    {periods.map((period, index) => (
                        <TableHead key={index} align="right">
                            <QuillDateColumnTitle
                                date={period.date}
                                secondaryDate={period.secondaryDate}
                                interval={interval || 'day'}
                                resolvedDateRange={insightData?.resolved_date_range}
                                timezone={timezone}
                                weekStartDay={weekStartDay}
                            />
                        </TableHead>
                    ))}
                </TableRow>
            }
        >
            {rows.map((row) => (
                <TableRow key={row.id}>
                    <TableCell sticky="left">
                        <QuillBreakdownValue
                            label={seriesLabel(row)}
                            breakdownFilter={breakdownFilter}
                            compareValue={row.compare_label && capitalizeFirstLetter(row.compare_label)}
                            swatch={<QuillSeriesSwatch color={rowColor(row)} />}
                        />
                    </TableCell>
                    {periods.map((period, index) => (
                        <QuillFunnelTrendsValueCell
                            key={index}
                            value={row.data[index] ?? 0}
                            isInProgress={period.isInProgress}
                            onOpenPersons={onOpenPersons ? () => onOpenPersons(row, index) : undefined}
                        />
                    ))}
                </TableRow>
            ))}
        </QuillDetailedResultsTable>
    )
}
