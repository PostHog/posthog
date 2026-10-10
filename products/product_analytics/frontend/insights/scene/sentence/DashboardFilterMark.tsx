import { Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

/** Marks a word that a dashboard's filters set. The note under the sentence gives the same explanation as the tooltip. */
export function DashboardFilterMark({ className }: { className?: string }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger delay={0} render={<span className={cn('inline-flex', className)} />}>
                {/* The app's own text-primary and border-primary are greys, so this reads quill's variables directly. */}
                <span
                    data-quill
                    className="inline-flex size-4 items-center justify-center rounded-full border-2 border-(--primary)/70 bg-(--card) text-xs font-bold text-(--primary)/70"
                >
                    <span aria-hidden>!</span>
                    <span className="sr-only">set by the dashboard</span>
                </span>
            </TooltipTrigger>
            <TooltipContent>Set by the dashboard's filters, not the saved insight.</TooltipContent>
        </Tooltip>
    )
}
