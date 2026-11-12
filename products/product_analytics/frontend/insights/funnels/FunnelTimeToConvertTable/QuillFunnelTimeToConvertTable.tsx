import { TableCell, TableHead, TableRow } from '@posthog/quill'

import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { QuillDetailedResultsTable } from 'products/product_analytics/frontend/insights/shared/QuillDetailedResultsTable'

import { TimeToConvertCompareRow } from './funnelTimeToConvertTableUtils'

interface QuillFunnelTimeToConvertTableProps {
    rows: TimeToConvertCompareRow[]
    isComparing: boolean
    loading: boolean
    medianTime?: number | null
    previousMedianTime?: number | null
}

export function QuillFunnelTimeToConvertTable({
    rows,
    isComparing,
    loading,
    medianTime,
    previousMedianTime,
}: QuillFunnelTimeToConvertTableProps): JSX.Element {
    return (
        <QuillDetailedResultsTable
            data-attr="funnel-time-to-convert-table"
            loading={loading}
            header={
                <>
                    {isComparing && (
                        <TableRow>
                            <TableHead />
                            <TableHead colSpan={2} className="border-l">
                                Current
                            </TableHead>
                            <TableHead colSpan={2} className="border-l">
                                Previous
                            </TableHead>
                        </TableRow>
                    )}
                    <TableRow>
                        <TableHead>Time to convert</TableHead>
                        <TableHead align="right" className={isComparing ? 'border-l' : undefined}>
                            Conversions
                        </TableHead>
                        <TableHead align="right">% of total</TableHead>
                        {isComparing && (
                            <>
                                <TableHead align="right" className="border-l">
                                    Conversions
                                </TableHead>
                                <TableHead align="right">% of total</TableHead>
                            </>
                        )}
                    </TableRow>
                </>
            }
            footer={
                medianTime ? (
                    <TableRow>
                        <TableCell colSpan={isComparing ? 5 : 3}>
                            <div className="flex items-center justify-between gap-4">
                                <span className="font-medium">Median time to convert</span>
                                <span>
                                    {humanFriendlyDuration(medianTime, { maxUnits: 3 })}
                                    {isComparing && (
                                        <span className="text-muted-foreground">
                                            {' '}
                                            (current) ·{' '}
                                            {previousMedianTime
                                                ? `${humanFriendlyDuration(previousMedianTime, { maxUnits: 3 })} (previous)`
                                                : '– (previous)'}
                                        </span>
                                    )}
                                </span>
                            </div>
                        </TableCell>
                    </TableRow>
                ) : undefined
            }
        >
            {rows.map((row) => (
                <TableRow key={row.id}>
                    <TableCell>
                        {`${humanFriendlyDuration(row.bin0, { maxUnits: 2 })} – ${humanFriendlyDuration(row.bin1, { maxUnits: 2 })}`}
                    </TableCell>
                    <TableCell align="right" className={isComparing ? 'border-l tabular-nums' : 'tabular-nums'}>
                        {humanFriendlyNumber(row.count)}
                    </TableCell>
                    <TableCell align="right" className="tabular-nums">
                        {row.label || '0%'}
                    </TableCell>
                    {isComparing && (
                        <>
                            <TableCell align="right" className="border-l tabular-nums">
                                {row.previous ? humanFriendlyNumber(row.previous.count) : '–'}
                            </TableCell>
                            <TableCell align="right" className="tabular-nums">
                                {row.previous?.label || '–'}
                            </TableCell>
                        </>
                    )}
                </TableRow>
            ))}
        </QuillDetailedResultsTable>
    )
}
