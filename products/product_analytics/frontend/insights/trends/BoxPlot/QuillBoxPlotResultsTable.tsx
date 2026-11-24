import { TableCell, TableHead, TableRow } from '@posthog/quill'

import { getSeriesColor } from 'lib/colors'

import { BoxPlotDatum } from '~/queries/schema/schema-general'

import { QuillDetailedResultsTable } from 'products/product_analytics/frontend/insights/shared/QuillDetailedResultsTable'
import { QuillSeriesSwatch } from 'products/product_analytics/frontend/insights/shared/QuillSeriesSwatch'

interface QuillBoxPlotResultsTableProps {
    data: BoxPlotDatum[]
    showSeries: boolean
    formatValue: (value: number) => string
}

const VALUE_COLUMNS: { title: string; key: 'min' | 'p25' | 'median' | 'mean' | 'p75' | 'max' }[] = [
    { title: 'Min', key: 'min' },
    { title: '25th percentile', key: 'p25' },
    { title: 'Median', key: 'median' },
    { title: 'Mean', key: 'mean' },
    { title: '75th percentile', key: 'p75' },
    { title: 'Max', key: 'max' },
]

export function QuillBoxPlotResultsTable({
    data,
    showSeries,
    formatValue,
}: QuillBoxPlotResultsTableProps): JSX.Element {
    return (
        <QuillDetailedResultsTable
            header={
                <TableRow>
                    {showSeries && <TableHead>Series</TableHead>}
                    <TableHead>Date</TableHead>
                    <TableHead align="right">Count</TableHead>
                    {VALUE_COLUMNS.map((column) => (
                        <TableHead key={column.key} align="right">
                            {column.title}
                        </TableHead>
                    ))}
                </TableRow>
            }
        >
            {data.map((datum) => (
                <TableRow key={`${datum.series_index ?? 0}-${datum.day}`}>
                    {showSeries && (
                        <TableCell>
                            <span className="flex items-center gap-2">
                                <QuillSeriesSwatch color={getSeriesColor(datum.series_index ?? 0)} />
                                {datum.series_label}
                            </span>
                        </TableCell>
                    )}
                    <TableCell>{datum.label}</TableCell>
                    <TableCell align="right" className="tabular-nums">
                        {datum.count?.toLocaleString() ?? '-'}
                    </TableCell>
                    {VALUE_COLUMNS.map((column) => (
                        <TableCell key={column.key} align="right" className="tabular-nums">
                            {formatValue(datum[column.key])}
                        </TableCell>
                    ))}
                </TableRow>
            ))}
        </QuillDetailedResultsTable>
    )
}
