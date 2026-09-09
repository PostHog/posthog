import clsx from 'clsx'

/**
 * Row-sized bar strip of a metric's trailing buckets, latest bucket in the accent color. The shared
 * `Sparkline` chart sizes its width from the bucket count and mounts a chart per row, which is too
 * heavy and too wide for a list of fifty rows, so this draws plain bars at a fixed width instead.
 */
export function ReportCardSparkline({ values }: { values: number[] }): JSX.Element {
    const maxValue = Math.max(...values, 1)

    return (
        <div
            className="flex h-4.5 w-18 flex-none items-end gap-0.5"
            aria-hidden
            data-attr="report-card-impact-sparkline"
        >
            {values.map((value, index) => (
                <div
                    key={index}
                    className={clsx(
                        'min-h-0.5 flex-1 rounded-[1px]',
                        index === values.length - 1 ? 'bg-accent' : 'bg-border-primary'
                    )}
                    style={{ height: `${Math.max(10, (value / maxValue) * 100)}%` }}
                />
            ))}
        </div>
    )
}
