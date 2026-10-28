import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function EndpointSceneSkeleton({ showTabs = true }: { showTabs?: boolean }): JSX.Element {
    return (
        <div role="status" className="flex flex-col gap-4">
            <span className="sr-only">Loading endpoint</span>
            <div aria-hidden="true" className="flex flex-col gap-4">
                <div className="flex flex-wrap gap-x-8 gap-y-4">
                    {['w-28', 'w-24', 'w-48', 'w-28', 'w-28'].map((width, index) => (
                        <div key={index} className="flex flex-col gap-2">
                            <LemonSkeleton className="h-3 w-24" />
                            <LemonSkeleton className={`h-6 ${width}`} />
                        </div>
                    ))}
                </div>
                {showTabs && (
                    <div className="flex flex-wrap gap-4 border-b pb-3">
                        <LemonSkeleton className="h-5 w-12" />
                        <LemonSkeleton className="h-5 w-28" />
                        <LemonSkeleton className="h-5 w-16" />
                        <LemonSkeleton className="h-5 w-24" />
                        <LemonSkeleton className="h-5 w-12" />
                        <LemonSkeleton className="h-5 w-16" />
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
