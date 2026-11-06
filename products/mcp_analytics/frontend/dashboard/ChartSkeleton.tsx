import { Skeleton } from '@posthog/quill-primitives'

export type ChartSkeletonKind = 'line' | 'columns' | 'bars' | 'shares'

const LINE_PATH = 'M0,70 C8,62 14,48 22,52 S36,30 46,36 S60,58 70,40 S86,18 100,24'
const COLUMN_HEIGHTS = [45, 60, 52, 75, 68, 85, 62, 78, 90, 70, 82, 55]
const BAR_WIDTHS = [92, 70, 54, 40, 28]
const SHARE_WIDTHS = [64, 42, 28, 18, 10]
const GRIDLINES = 4

function PlotFrame({ xTicks, children }: { xTicks: number; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-1 gap-2">
            <div className="flex flex-col justify-between pb-6">
                {Array.from({ length: GRIDLINES }, (_, i) => (
                    <Skeleton key={i} className="h-2.5 w-6" />
                ))}
            </div>
            <div className="flex flex-1 flex-col">
                <div className="relative flex-1">
                    <div className="absolute inset-0 flex flex-col justify-between">
                        {Array.from({ length: GRIDLINES }, (_, i) => (
                            <div key={i} className="border-t border-dashed border-border" />
                        ))}
                    </div>
                    {children}
                </div>
                <div className="flex h-6 items-end justify-between">
                    {Array.from({ length: xTicks }, (_, i) => (
                        <Skeleton key={i} className="h-2.5 w-8" />
                    ))}
                </div>
            </div>
        </div>
    )
}

function LineSkeleton(): JSX.Element {
    return (
        <PlotFrame xTicks={6}>
            <svg
                className="absolute inset-0 h-full w-full animate-pulse"
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
                aria-hidden
            >
                <path
                    d={LINE_PATH}
                    fill="none"
                    stroke="color-mix(in oklab, var(--foreground) 12%, transparent)"
                    strokeWidth={3}
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                />
            </svg>
        </PlotFrame>
    )
}

function ColumnsSkeleton(): JSX.Element {
    return (
        <PlotFrame xTicks={6}>
            <div className="absolute inset-0 flex items-end justify-around gap-2 px-1">
                {COLUMN_HEIGHTS.map((height, i) => (
                    <Skeleton key={i} className="flex-1 rounded-b-none" style={{ height: `${height}%` }} />
                ))}
            </div>
        </PlotFrame>
    )
}

function BarsSkeleton(): JSX.Element {
    return (
        <div className="flex flex-1 flex-col">
            <div className="flex flex-1 flex-col justify-around">
                {BAR_WIDTHS.map((width, i) => (
                    <div key={i} className="flex items-center gap-3">
                        <Skeleton className="h-2.5 w-20 shrink-0" />
                        <div className="flex-1">
                            <Skeleton className="h-6" style={{ width: `${width}%` }} />
                        </div>
                    </div>
                ))}
            </div>
            <div className="ml-23 flex h-6 items-end justify-between">
                {Array.from({ length: 5 }, (_, i) => (
                    <Skeleton key={i} className="h-2.5 w-6" />
                ))}
            </div>
        </div>
    )
}

function SharesSkeleton(): JSX.Element {
    return (
        <div className="flex flex-1 flex-col gap-4 pt-2">
            <div className="flex justify-between">
                <Skeleton className="h-2.5 w-14" />
                <Skeleton className="h-2.5 w-20" />
            </div>
            {SHARE_WIDTHS.map((width, i) => (
                <div key={i} className="flex flex-col gap-1.5">
                    <div className="flex justify-between">
                        <Skeleton className="h-2.5 w-24" />
                        <Skeleton className="h-2.5 w-16" />
                    </div>
                    <Skeleton className="h-2" style={{ width: `${width}%` }} />
                </div>
            ))}
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
        <div className="flex flex-1 flex-col py-2" aria-busy aria-label="Loading chart">
            <Variant />
        </div>
    )
}
