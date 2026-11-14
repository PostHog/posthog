import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { RolloutStep } from './releaseRollout'
import { Scale, rolloutSegments } from './releaseTracks'

const LABEL_ROOM = 34
const DATED_LABEL_ROOM = 104

function percentLabel(step: RolloutStep): string {
    return step.label === 'Everyone' ? '100%' : step.label
}

function dateRange(step: RolloutStep): string {
    const from = dayjs(step.from)
    if (step.upcoming) {
        return `Scheduled for ${from.format('D MMM')}`
    }
    const to = dayjs(step.to)
    return to.isSame(dayjs(), 'day') || to.isAfter(dayjs())
        ? `Since ${from.format('D MMM')}`
        : `${from.format('D MMM')} to ${to.format('D MMM')}`
}

export function ReleaseRolloutBar({
    steps,
    scale,
    color,
    top,
    height,
    stickyOffset = 0,
}: {
    steps: RolloutStep[]
    scale: Scale
    color: string
    top: number
    height: number
    stickyOffset?: number
}): JSX.Element | null {
    const segments = rolloutSegments(steps, scale, dayjs())
    const end = scale.days * scale.day
    if (!segments.length) {
        return null
    }
    return (
        <TooltipProvider>
            {segments.map(({ step, left, width, projected }, index) => {
                const percent = Math.max(0, Math.min(100, step.percent))
                const dashed = step.upcoming || projected
                const fill = dashed ? 8 : 14 + percent * 0.46
                const isFirst = index === 0 && !dayjs(step.from).isBefore(scale.start, 'day')
                const isLast = index === segments.length - 1 && left + width < end
                return (
                    <Tooltip key={`${step.from}-${index}`}>
                        <TooltipTrigger
                            render={
                                <div
                                    className={cn(
                                        'absolute flex items-center border-y text-[10px] font-semibold tabular-nums text-foreground',
                                        dashed && 'border-dashed',
                                        isFirst && 'rounded-l-full border-l',
                                        isLast && 'rounded-r-full border-r'
                                    )}
                                    style={{
                                        left,
                                        width,
                                        top,
                                        height,
                                        clipPath: 'inset(0)',
                                        backgroundColor: `color-mix(in oklab, ${color} ${fill}%, transparent)`,
                                        borderColor: `color-mix(in oklab, ${color} ${dashed ? 60 : 35}%, transparent)`,
                                        boxShadow:
                                            index === 0 || projected
                                                ? undefined
                                                : `inset 1px 0 0 color-mix(in oklab, ${color} 40%, transparent)`,
                                    }}
                                    data-attr="release-rollout-step"
                                />
                            }
                        >
                            {!projected && width >= LABEL_ROOM && (
                                <span
                                    className="sticky truncate px-1.5"
                                    style={{ left: stickyOffset, maxWidth: width }}
                                >
                                    {step.upcoming && width >= DATED_LABEL_ROOM
                                        ? `${percentLabel(step)} on ${dayjs(step.from).format('D MMM')}`
                                        : percentLabel(step)}
                                </span>
                            )}
                        </TooltipTrigger>
                        <TooltipContent>
                            <span className="flex flex-col gap-0.5">
                                <span className="font-semibold">
                                    {step.label === 'Everyone' ? 'Everyone' : `${percentLabel(step)} rollout`}
                                </span>
                                <span className="opacity-70">{dateRange(step)}</span>
                            </span>
                        </TooltipContent>
                    </Tooltip>
                )
            })}
        </TooltipProvider>
    )
}
