import { LemonModal, LemonSkeleton } from '@posthog/lemon-ui'

/** Holds the create form's geometry while its lazy-loaded bundle is downloading. */
export function ScoutCreateModalSkeleton(): JSX.Element {
    return (
        <LemonModal
            isOpen
            onClose={() => {}}
            title="Create a scout"
            description="Define what the scout should investigate and how often it should run."
            width={720}
            footer={
                <>
                    <LemonSkeleton.Button />
                    <LemonSkeleton.Button />
                </>
            }
        >
            <div className="flex flex-col gap-4" aria-label="Loading scout form">
                <ScoutFormFieldSkeleton className="h-10" />
                <ScoutFormFieldSkeleton className="h-16" />
                <ScoutFormFieldSkeleton className="h-10" />
                <ScoutFormFieldSkeleton className="h-48" />
                <div className="flex flex-col gap-3 border-t border-primary pt-4">
                    <LemonSkeleton className="h-4 w-24 rounded" />
                    <ScoutFormFieldSkeleton className="h-10" />
                </div>
            </div>
        </LemonModal>
    )
}

function ScoutFormFieldSkeleton({ className }: { className: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <LemonSkeleton className="h-3 w-24 rounded" />
            <LemonSkeleton className={`w-full rounded ${className}`} />
        </div>
    )
}
