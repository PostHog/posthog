import { cn } from 'lib/ui/quill'

export function HogFlowTreeBranchIndicator({ color, className }: { color: string; className?: string }): JSX.Element {
    return (
        <span
            aria-hidden="true"
            className={cn('pointer-events-none absolute -start-4 w-0.5 rounded-full', className)}
            style={{ backgroundColor: color }}
        />
    )
}
