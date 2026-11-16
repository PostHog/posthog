import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { LANE_CARD_CLASS, ReleaseLaneCard } from './ReleaseLaneCard'
import { RolloutStep } from './releaseRollout'
import { Lane, Scale, rolloutSegments } from './releaseTracks'

const LABEL_ROOM = 34
const DATED_LABEL_ROOM = 104

function percentLabel(step: RolloutStep): string {
    return step.label === 'Everyone' ? '100%' : step.label
}

export function ReleaseRolloutBar({
    steps,
    scale,
    color,
    top,
    height,
    stickyOffset = 0,
    lane,
}: {
    steps: RolloutStep[]
    scale: Scale
    color: string
    top: number
    height: number
    stickyOffset?: number
    lane?: Lane
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
                    <Tooltip key={`${step.from}-${index}`} trackCursorAxis="x">
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
                        <TooltipContent sideOffset={8} className={LANE_CARD_CLASS}>
                            <ReleaseLaneCard
                                lane={lane}
                                step={step}
                                next={steps.find((item) => item.upcoming && item.from > step.from)}
                            />
                        </TooltipContent>
                    </Tooltip>
                )
            })}
        </TooltipProvider>
    )
}
