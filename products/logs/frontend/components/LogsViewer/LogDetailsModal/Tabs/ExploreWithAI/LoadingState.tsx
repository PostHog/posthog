import { IconAIText } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'

export function LoadingState(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="flex items-center gap-2 text-muted">
                <IconAIText className="text-lg animate-pulse" />
                <span>Analyzing log... Hold on tight!</span>
            </div>
            <LemonSkeleton className="h-12 w-full" />
            <LemonSkeleton className="h-6 w-3/4" />
            <LemonSkeleton className="h-4 w-full" />
            <LemonSkeleton className="h-4 w-full" />
            <LemonSkeleton className="h-4 w-2/3" />
            <div className="flex gap-2 mt-2">
                <LemonSkeleton className="h-8 w-24" />
                <LemonSkeleton className="h-8 w-32" />
                <LemonSkeleton className="h-8 w-28" />
            </div>
        </div>
    )
}
