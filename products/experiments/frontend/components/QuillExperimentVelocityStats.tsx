import { IconInfo, IconTrending } from '@posthog/icons'
import { Button, Separator, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { IconTrendingDown } from 'lib/lemon-ui/icons'

import { VELOCITY_HELP, useExperimentVelocity } from './ExperimentVelocityStats'

function Stat({ value, label, children }: { value: number; label: string; children?: React.ReactNode }): JSX.Element {
    return (
        <span className="flex items-center gap-1 whitespace-nowrap">
            <Text size="xs" weight="semibold" render={<span />}>
                {value}
            </Text>
            {children}
            <Text size="xs" variant="muted" render={<span />}>
                {label}
            </Text>
        </span>
    )
}

/** The velocity summary in one line, as tall as the list's search field. */
export function QuillExperimentVelocityStats(): JSX.Element | null {
    const velocity = useExperimentVelocity()

    if (!velocity) {
        return null
    }

    const { launched, percentChange, running, completed } = velocity

    return (
        <div
            className="flex h-7 items-center gap-3 rounded-md border border-border bg-card pr-3 pl-1"
            data-attr="experiments-velocity"
        >
            <span className="flex items-center">
                <Text size="xs" weight="semibold" render={<span className="pl-1.5" />}>
                    Velocity
                </Text>
                <Tooltip>
                    <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="About velocity" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-80">{VELOCITY_HELP}</TooltipContent>
                </Tooltip>
            </span>
            <Separator orientation="vertical" className="h-4" />
            <Stat value={launched} label="launched (30d)">
                {percentChange !== 0 && (
                    <span
                        className={cn(
                            'flex items-center gap-0.5 text-xs font-medium',
                            percentChange > 0 ? 'text-success-foreground' : 'text-destructive-foreground'
                        )}
                    >
                        {percentChange > 0 ? <IconTrending /> : <IconTrendingDown />}
                        {Math.abs(percentChange)}%
                    </span>
                )}
            </Stat>
            <Stat value={running} label="running" />
            <Stat value={completed} label="completed" />
        </div>
    )
}
