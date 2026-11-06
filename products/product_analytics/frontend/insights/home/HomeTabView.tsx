import type { ReactNode } from 'react'

import { HomeTabChartCard } from './HomeTabChartCard'
import type { HomeTabViewRows } from './homeTabViewCharts'

export function HomeTabView({
    rows,
    label,
    note,
}: {
    rows: HomeTabViewRows
    label: string
    note?: ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-3" aria-label={label}>
            {rows.map((row, rowIndex) => (
                <div
                    key={row.map(({ option }) => option.key).join('.')}
                    className={
                        row.length > 1
                            ? 'grid min-w-0 grid-cols-1 gap-3 @min-[44rem]/home-overview:grid-cols-2'
                            : 'min-w-0'
                    }
                >
                    {row.map(({ option, size, source }) => (
                        <HomeTabChartCard
                            key={option.key}
                            option={option}
                            size={size}
                            source={source}
                            loadPriority={rowIndex}
                        />
                    ))}
                </div>
            ))}
            {note && <p className="m-0 text-xs text-secondary">{note}</p>}
        </section>
    )
}
