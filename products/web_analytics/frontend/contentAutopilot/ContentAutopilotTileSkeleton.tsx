import { Skeleton } from '@posthog/quill'

import { AiVisibilityCard } from './AiVisibilityCard'

/** A loading tile with its real title, so the page reads the same before and after its data arrives. */
export const ContentAutopilotTileSkeleton = ({
    title,
    bodyClassName,
    skeletonClassName = 'h-48 w-full',
    withInsightButton = false,
}: {
    title: string
    bodyClassName?: string
    skeletonClassName?: string
    withInsightButton?: boolean
}): JSX.Element => (
    <AiVisibilityCard
        title={title}
        // The loaded query tiles put an "Open as insight" button here, which sets the header height.
        actions={withInsightButton ? <Skeleton className="h-7 w-32" /> : undefined}
    >
        <div className={bodyClassName} aria-busy>
            <Skeleton className={skeletonClassName} />
        </div>
    </AiVisibilityCard>
)
