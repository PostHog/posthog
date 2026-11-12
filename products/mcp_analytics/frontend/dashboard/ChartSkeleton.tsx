import { cn, Skeleton } from '@posthog/quill-primitives'

export type ChartSkeletonKind = 'line' | 'columns' | 'bars' | 'shares'

interface PlotLayout {
    yAxis: string
    plot: string
    xAxis: string
}

// quill-charts' time series margins (top 16, right 16, bottom 32) with a short y-axis label (left 50).
const TIME_SERIES_LAYOUT: PlotLayout = {
    yAxis: 'top-4 bottom-8 left-0 w-[44px]',
    plot: 'top-4 right-4 bottom-8 left-[50px]',
    xAxis: 'bottom-0 left-[50px] right-4 h-6',
}
// ToolErrorRateChart's margins (top 4, right 20, bottom 22), with a y-axis wide enough for a typical tool name.
const HORIZONTAL_BAR_LAYOUT: PlotLayout = {
    yAxis: 'top-1 bottom-[22px] left-0 w-[118px]',
    plot: 'top-1 right-5 bottom-[22px] left-[124px]',
    xAxis: 'bottom-0 left-[124px] right-5 h-3.5',
}
// quill-charts' default band padding of 0.2 leaves each column 80% of its band.
const COLUMN_BAND_FILL = 0.8
// ToolErrorRateChart's minBandSize config leaves each bar about 65% of its band.
const BAR_BAND_FILL = 0.65

const Y_TICKS = 5
const DAYS = 7
const COLUMN_HEIGHTS = [52, 60, 61, 60, 66, 70, 72]
const LINE_PATH = 'M0,30 C10,28 20,26 33,22 S50,24 55,25 S70,18 80,15 S95,12 100,11'
const BAR_WIDTHS = [88, 64, 46, 32, 20, 12]
const BAR_LABEL_WIDTHS = [80, 64, 40, 76, 72, 96]
const PERCENT_TICKS = 9
const SHARE_WIDTHS = [36, 24, 14, 10, 7, 4, 5]
const SHARE_LABEL_WIDTHS = [80, 72, 100, 40, 44, 52, 92]

export const SKELETON_COLOR = 'color-mix(in oklab, var(--foreground) 12%, transparent)'
export const SKELETON_TRACK_COLOR = 'color-mix(in oklab, var(--foreground) 6%, transparent)'

function TickLabels({ count, axis, className }: { count: number; axis: 'x' | 'y'; className: string }): JSX.Element {
    return (
        <>
            {Array.from({ length: count }, (_, i) => {
                const offset = `${(i / (count - 1)) * 100}%`
                return (
                    <Skeleton
                        key={i}
                        className={cn(
                            'absolute h-2.5',
                            axis === 'x' ? '-translate-x-1/2' : 'right-0 translate-y-1/2',
                            className
                        )}
                        style={axis === 'x' ? { left: offset } : { bottom: offset }}
                    />
                )
            })}
        </>
    )
}

// A line chart puts its x ticks on the data points, a column chart in the middle of each band.
function TimeSeriesFrame({ xTicks, children }: { xTicks: 'points' | 'bands'; children: React.ReactNode }): JSX.Element {
    const layout = TIME_SERIES_LAYOUT
    return (
        <div className="relative flex-1">
            <div className={cn('absolute', layout.yAxis)}>
                <TickLabels count={Y_TICKS} axis="y" className="w-7" />
            </div>
            <div className={cn('absolute border-b border-l border-border', layout.plot)}>
                <div className="absolute inset-0 flex flex-col justify-between">
                    {Array.from({ length: Y_TICKS - 1 }, (_, i) => (
                        <div key={i} className="border-t border-dashed border-border" />
                    ))}
                    <div />
                </div>
                {children}
            </div>
            <div className={cn('absolute', layout.xAxis)}>
                {xTicks === 'points' ? (
                    <TickLabels count={DAYS} axis="x" className="w-9" />
                ) : (
                    <div className="flex">
                        {Array.from({ length: DAYS }, (_, i) => (
                            <div key={i} className="flex flex-1 justify-center">
                                <Skeleton className="h-2.5 w-9" />
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}

function LineSkeleton(): JSX.Element {
    return (
        <TimeSeriesFrame xTicks="points">
            <svg
                className="absolute inset-0 h-full w-full animate-pulse"
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
                aria-hidden
            >
                <path
                    d={LINE_PATH}
                    fill="none"
                    stroke={SKELETON_COLOR}
                    strokeWidth={2}
                    vectorEffect="non-scaling-stroke"
                />
            </svg>
        </TimeSeriesFrame>
    )
}

function ColumnsSkeleton(): JSX.Element {
    return (
        <TimeSeriesFrame xTicks="bands">
            <div className="absolute inset-0 flex items-end">
                {COLUMN_HEIGHTS.map((height, i) => (
                    <div key={i} className="flex h-full flex-1 items-end justify-center">
                        <Skeleton
                            className="rounded-b-none"
                            style={{ width: `${COLUMN_BAND_FILL * 100}%`, height: `${height}%` }}
                        />
                    </div>
                ))}
            </div>
        </TimeSeriesFrame>
    )
}

function BarsSkeleton(): JSX.Element {
    const layout = HORIZONTAL_BAR_LAYOUT
    return (
        <div className="relative flex-1">
            <div className={cn('absolute flex flex-col', layout.yAxis)}>
                {BAR_LABEL_WIDTHS.map((width, i) => (
                    <div key={i} className="flex flex-1 items-center justify-end">
                        <Skeleton className="h-2.5" style={{ width }} />
                    </div>
                ))}
            </div>
            <div className={cn('absolute border-b border-l border-border', layout.plot)}>
                <div className="absolute inset-0 flex justify-between">
                    {Array.from({ length: PERCENT_TICKS }, (_, i) => (
                        <div key={i} className={cn('border-l border-dashed border-border', i === 0 && 'border-none')} />
                    ))}
                </div>
                <div className="absolute inset-0 flex flex-col">
                    {BAR_WIDTHS.map((width, i) => (
                        <div key={i} className="flex flex-1 items-center">
                            <Skeleton
                                className="rounded-l-none"
                                style={{ width: `${width}%`, height: `${BAR_BAND_FILL * 100}%` }}
                            />
                        </div>
                    ))}
                </div>
            </div>
            <div className={cn('absolute', layout.xAxis)}>
                <TickLabels count={PERCENT_TICKS} axis="x" className="w-6" />
            </div>
        </div>
    )
}

// Mirrors BarList's rows: a 16px label line, then a 10px track 20px below the row's top, every 40px.
function SharesSkeleton(): JSX.Element {
    return (
        <div className="flex flex-1 flex-col">
            <div className="flex h-4 items-center justify-between">
                <Skeleton className="h-2.5 w-16" />
                <Skeleton className="h-2.5 w-24" />
            </div>
            <div className="pt-2">
                {SHARE_WIDTHS.map((width, i) => (
                    <div key={i} className="flex h-10 flex-col">
                        <div className="flex h-4 items-center justify-between">
                            <div className="flex items-center gap-1.5">
                                <Skeleton className="size-4 rounded-sm" />
                                <Skeleton className="h-2.5" style={{ width: SHARE_LABEL_WIDTHS[i] }} />
                            </div>
                            <Skeleton className="h-2.5 w-28" />
                        </div>
                        <div className="mt-1 h-2.5 overflow-hidden rounded-sm bg-[color-mix(in_oklab,var(--foreground)_6%,transparent)]">
                            <Skeleton className="h-full rounded-none" style={{ width: `${width}%` }} />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}

const SKELETONS: Record<ChartSkeletonKind, () => JSX.Element> = {
    line: LineSkeleton,
    columns: ColumnsSkeleton,
    bars: BarsSkeleton,
    shares: SharesSkeleton,
}

export function ChartSkeleton({ kind }: { kind: ChartSkeletonKind }): JSX.Element {
    const Variant = SKELETONS[kind]
    return (
        <div className="flex flex-1 flex-col" aria-busy aria-label="Loading chart">
            <Variant />
        </div>
    )
}
