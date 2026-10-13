import {
    Button,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { BandFilter, ExceptionBand } from './releaseBreakdown'

const COLUMN_COUNT = 3

function formatShare(share: number): string {
    if (share > 0 && share < 0.5) {
        return '<1%'
    }
    return `${Math.round(share)}%`
}

function BandLabel({
    band,
    onSelectBand,
}: {
    band: ExceptionBand
    onSelectBand: (filters: BandFilter[]) => void
}): JSX.Element {
    const swatch = (
        // eslint-disable-next-line react/forbid-dom-props
        <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ backgroundColor: band.color }} />
    )
    if (!band.filters) {
        return (
            <div className="flex min-w-0 items-center gap-1.5">
                {swatch}
                <Text size="xs" variant="muted" className="truncate">
                    {band.label}
                </Text>
            </div>
        )
    }
    return (
        <Button
            variant="default"
            size="sm"
            className="h-6 w-full min-w-0 justify-start gap-1.5 px-1.5 text-xs"
            data-attr="error-tracking-insights-band-filter"
            tooltip="Filter this tab down to it"
            onClick={() => onSelectBand(band.filters as BandFilter[])}
        >
            {swatch}
            <span className="truncate">{band.label}</span>
        </Button>
    )
}

function BandRows({
    bands,
    loading,
    onSelectBand,
}: {
    bands: ExceptionBand[]
    loading: boolean
    onSelectBand: (filters: BandFilter[]) => void
}): JSX.Element {
    if (loading) {
        return (
            <TableBody>
                <TableRow>
                    <TableCell colSpan={COLUMN_COUNT}>
                        <div className="space-y-2 py-1">
                            {Array.from({ length: 4 }).map((_, index) => (
                                <Skeleton key={index} className="h-3.5 w-full" />
                            ))}
                        </div>
                    </TableCell>
                </TableRow>
            </TableBody>
        )
    }
    if (bands.length === 0) {
        return <TableEmpty className="py-6 text-secondary">No exceptions in this period.</TableEmpty>
    }
    return (
        <TableBody>
            {bands.map((band) => (
                <TableRow key={band.key}>
                    <TableCell expand>
                        <BandLabel band={band} onSelectBand={onSelectBand} />
                    </TableCell>
                    <TableCell align="right" className="tabular-nums">
                        {humanFriendlyLargeNumber(band.total)}
                    </TableCell>
                    <TableCell align="right" className="tabular-nums text-secondary">
                        {formatShare(band.share)}
                    </TableCell>
                </TableRow>
            ))}
        </TableBody>
    )
}

export function ExceptionBandTable({
    bands,
    loading,
    columnLabel,
    onSelectBand,
}: {
    bands: ExceptionBand[]
    loading: boolean
    /** Header of the first column, naming what the rows are split by. */
    columnLabel: string
    onSelectBand: (filters: BandFilter[]) => void
}): JSX.Element {
    return (
        <div className="overflow-x-auto">
            <Table fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead expand>{columnLabel}</TableHead>
                        <TableHead align="right">Exceptions</TableHead>
                        <TableHead align="right">Share</TableHead>
                    </TableRow>
                </TableHeader>
                <BandRows bands={bands} loading={loading} onSelectBand={onSelectBand} />
            </Table>
        </div>
    )
}
