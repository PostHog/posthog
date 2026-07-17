import { LemonSkeleton } from '@posthog/lemon-ui'

import { ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'

/** Skeleton for the scene side panel's task-info block — mirrors the four labelled rows. */
export function TaskPanelSkeleton(): JSX.Element {
    return (
        <ScenePanelInfoSection>
            <div className="flex flex-col gap-3">
                <div>
                    <div className="text-xs text-muted mb-1">Task ID</div>
                    <LemonSkeleton className="h-5 w-24" />
                </div>
                <div>
                    <div className="text-xs text-muted mb-1">Repository</div>
                    <LemonSkeleton className="h-5 w-36" />
                </div>
                <div>
                    <div className="text-xs text-muted mb-1">Created by</div>
                    <LemonSkeleton className="h-5 w-32" />
                </div>
                <div>
                    <div className="text-xs text-muted mb-1">Created</div>
                    <LemonSkeleton className="h-5 w-40" />
                </div>
            </div>
        </ScenePanelInfoSection>
    )
}

/** Skeleton for the title-bar action buttons (Open in PostHog Code / View PR / Run). */
export function TaskHeaderActionsSkeleton(): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <LemonSkeleton className="h-7 w-40" />
            <LemonSkeleton className="h-7 w-24" />
        </div>
    )
}

/** Skeleton for the run created/completed/duration metadata row. */
export function TaskRunMetadataSkeleton(): JSX.Element {
    return (
        <div className="items-center gap-4 hidden lg:flex">
            <LemonSkeleton className="h-4 w-32" />
            <LemonSkeleton className="h-4 w-32" />
        </div>
    )
}
