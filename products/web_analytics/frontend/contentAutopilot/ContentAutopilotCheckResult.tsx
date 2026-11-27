import { Dot, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { positionLabel } from './promptReport'

const Result = ({
    variant,
    children,
}: {
    variant: 'destructive' | 'success' | 'default'
    children: React.ReactNode
}): JSX.Element => (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
        <Dot variant={variant} aria-hidden />
        <span>{children}</span>
    </span>
)

export const ContentAutopilotCheckResult = ({
    cited,
    checkFailed,
    position,
}: {
    cited: boolean
    checkFailed: boolean
    position?: number | null
}): JSX.Element =>
    checkFailed ? (
        <Result variant="destructive">Failed</Result>
    ) : cited && position ? (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex" />}>
                <Result variant="success">Cited {positionLabel(position)}</Result>
            </TooltipTrigger>
            <TooltipContent>Your site is source {position} in this answer</TooltipContent>
        </Tooltip>
    ) : cited ? (
        <Result variant="success">Cited</Result>
    ) : (
        <Result variant="default">
            <span className="text-muted-foreground">Not cited</span>
        </Result>
    )
