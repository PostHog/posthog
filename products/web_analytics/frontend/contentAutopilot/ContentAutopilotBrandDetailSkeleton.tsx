import { Skeleton } from '@posthog/quill'

const KPI_CARDS = 4
const TABS = 4
const ROWS = 6

/** A brand's page while it loads, laid out like the loaded page, so nothing moves when the numbers arrive. */
export const ContentAutopilotBrandDetailSkeleton = (): JSX.Element => (
    <div className="flex flex-col gap-4" data-attr="content-autopilot-brand-detail-loading">
        <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-5 w-20" />
        </div>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-2">
            {Array.from({ length: KPI_CARDS }, (_, index) => (
                <div key={index} className="flex min-w-0 flex-col gap-2 rounded border p-3">
                    <Skeleton className="h-3 w-16" />
                    <Skeleton className="h-9 w-24" />
                    <Skeleton className="h-3 w-20" />
                </div>
            ))}
        </div>
        <div className="flex gap-4 border-b pb-2">
            {Array.from({ length: TABS }, (_, index) => (
                <Skeleton key={index} className="h-5 w-16" />
            ))}
        </div>
        <div className="flex flex-col gap-2">
            {Array.from({ length: ROWS }, (_, index) => (
                <Skeleton key={index} className="h-6 w-full" />
            ))}
        </div>
    </div>
)
