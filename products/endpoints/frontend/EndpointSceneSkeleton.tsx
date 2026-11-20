import { Skeleton } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

const FIELD_WIDTHS = ['w-28', 'w-24', 'w-48', 'w-28', 'w-28']
const TAB_WIDTHS = ['w-12', 'w-28', 'w-16', 'w-24', 'w-12', 'w-16']

export function EndpointSceneSkeleton({ showTabs = true }: { showTabs?: boolean }): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div role="status" className="flex flex-col gap-4" data-quill>
                <span className="sr-only">Loading endpoint</span>
                <div aria-hidden="true" className="flex flex-col gap-4">
                    <div className="flex flex-wrap gap-x-8 gap-y-4">
                        {FIELD_WIDTHS.map((width, index) => (
                            <div key={index} className="flex flex-col gap-2">
                                <Skeleton className="h-3 w-24" />
                                <Skeleton className={`h-6 ${width}`} />
                            </div>
                        ))}
                    </div>
                    {showTabs && (
                        <div className="flex flex-wrap gap-4 border-b border-border pb-3">
                            {TAB_WIDTHS.map((width, index) => (
                                <Skeleton key={index} className={`h-5 ${width}`} />
                            ))}
                        </div>
                    )}
                    <div className="overflow-hidden rounded-lg border border-border">
                        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-3">
                            <Skeleton className="h-5 w-24" />
                            <Skeleton className="h-7 w-20" />
                        </div>
                        <div className="flex h-96 flex-col gap-3 p-4">
                            <Skeleton className="h-4 w-1/4" />
                            <Skeleton className="h-4 w-2/3" />
                            <Skeleton className="h-4 w-1/2" />
                            <Skeleton className="h-4 w-3/5" />
                            <Skeleton className="h-4 w-1/3" />
                        </div>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div role="status" className="flex flex-col gap-4">
            <span className="sr-only">Loading endpoint</span>
            <div aria-hidden="true" className="flex flex-col gap-4">
                <div className="flex flex-wrap gap-x-8 gap-y-4">
                    {FIELD_WIDTHS.map((width, index) => (
                        <div key={index} className="flex flex-col gap-2">
                            <LemonSkeleton className="h-3 w-24" />
                            <LemonSkeleton className={`h-6 ${width}`} />
                        </div>
                    ))}
                </div>
                {showTabs && (
                    <div className="flex flex-wrap gap-4 border-b pb-3">
                        {TAB_WIDTHS.map((width, index) => (
                            <LemonSkeleton key={index} className={`h-5 ${width}`} />
                        ))}
                    </div>
                )}
                <div className="overflow-hidden rounded border">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3">
                        <LemonSkeleton className="h-5 w-24" />
                        <LemonSkeleton.Button className="w-20" size="small" />
                    </div>
                    <div className="flex h-96 flex-col gap-3 p-4">
                        <LemonSkeleton className="h-4 w-1/4" />
                        <LemonSkeleton className="h-4 w-2/3" />
                        <LemonSkeleton className="h-4 w-1/2" />
                        <LemonSkeleton className="h-4 w-3/5" />
                        <LemonSkeleton className="h-4 w-1/3" />
                    </div>
                </div>
            </div>
        </div>
    )
}
