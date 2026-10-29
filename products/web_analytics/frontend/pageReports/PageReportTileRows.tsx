import clsx from 'clsx'

import { PageReportTileRow } from 'scenes/web-analytics/pageReportsLogic'
import { QueryTileItem } from 'scenes/web-analytics/WebAnalyticsDashboard'

const ROW_CLASS = 'grid grid-cols-1 @min-[44rem]/main-content:grid-cols-2 @min-[64rem]/main-content:grid-cols-6 gap-3'

const TRUNCATED_LABEL_COLUMN = clsx(
    '[&_tbody_td:first-child]:max-w-0 [&_tbody_td:first-child]:w-full [&_tbody_td:first-child]:truncate',
    '[&_thead_th:first-child]:max-w-0 [&_thead_th:first-child]:w-full [&_thead_th:first-child]:whitespace-normal [&_thead_th:first-child_*]:whitespace-normal'
)

const WIDE_SPAN: Record<number, string> = {
    2: '@min-[64rem]/main-content:col-span-2',
    3: '@min-[64rem]/main-content:col-span-3',
    4: '@min-[64rem]/main-content:col-span-4',
    6: '@min-[64rem]/main-content:col-span-6',
}

const FULL_ROW_ON_TWO_COLUMNS = '@min-[44rem]/main-content:col-span-2'

function wideSpan(count: number, index: number): number {
    if (count === 1) {
        return 6
    }
    if (count === 2 || count === 4) {
        return 3
    }
    if (count === 5) {
        return index < 3 ? 2 : 3
    }
    return 2
}

function tileSpanClass(row: PageReportTileRow, index: number): string {
    const count = row.tiles.length
    if (row.variant === 'feature') {
        return clsx(FULL_ROW_ON_TWO_COLUMNS, WIDE_SPAN[count === 1 ? 6 : index === 0 ? 4 : 2])
    }
    const isLoneTileOnTwoColumns = count % 2 === 1 && index === count - 1
    return clsx(isLoneTileOnTwoColumns && FULL_ROW_ON_TWO_COLUMNS, WIDE_SPAN[wideSpan(count, index)])
}

export function PageReportTileRows({ rows }: { rows: PageReportTileRow[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            {rows.map((row) => (
                <div
                    key={row.key}
                    className={clsx(ROW_CLASS, TRUNCATED_LABEL_COLUMN)}
                    data-attr={`page-report-row-${row.key}`}
                >
                    {row.tiles.map((tile, index) => (
                        <div
                            key={tile.tileId}
                            className={clsx(
                                '@container/page-report-tile min-w-0 flex flex-col',
                                tileSpanClass(row, index)
                            )}
                        >
                            <QueryTileItem tile={tile} />
                        </div>
                    ))}
                </div>
            ))}
        </div>
    )
}
