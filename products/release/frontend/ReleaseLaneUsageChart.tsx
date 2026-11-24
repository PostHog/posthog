import { useValues } from 'kea'

import { Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { UsageKind, UsageTarget } from './releaseLaneUsage'
import { releaseLaneUsageLogic } from './releaseLaneUsageLogic'
import { SPAN_LOOK, Scale, x } from './releaseTracks'
import { ReleaseVariantChart } from './ReleaseVariantChart'

const CAPTION: Record<UsageKind, string> = {
    flag: 'Users whose app checked this flag, per day',
    experiment: 'Users in the experiment, per day',
    early_access: 'Users who opted in or out, per day',
    survey: 'Users who answered, per day',
}

const EMPTY: Record<UsageKind, string> = {
    flag: 'No app checked this flag in this period. Your code may not use it yet.',
    experiment: 'No one entered the experiment in this period.',
    early_access: 'No one opted in or out in this period.',
    survey: 'No one answered in this period.',
}

const HEADER = 52
const FOOTER = 8

export function ReleaseLaneUsageChart({
    target,
    scale,
    height,
    stickyOffset = 0,
}: {
    target: UsageTarget
    scale: Scale
    height: number
    stickyOffset?: number
}): JSX.Element {
    const { usage, usageLoading, insights } = useValues(
        releaseLaneUsageLogic({ target, from: scale.start.format('YYYY-MM-DD') })
    )
    const days = (usage?.days ?? []).filter((day) => !dayjs(day.day).isBefore(scale.start, 'day'))
    const peak = days.reduce((max, day) => (day.users > max.users ? day : max), { day: '', users: 0, total: 0 })
    const area = height - HEADER - FOOTER
    const color = SPAN_LOOK[target.kind === 'early_access' ? 'early_access' : target.kind].color

    if (insights?.kind === 'experiment' && insights.metricName && insights.series.length) {
        return (
            <ReleaseVariantChart
                series={insights.series}
                cumulative={insights.cumulative}
                metricName={insights.metricName}
                scale={scale}
                height={height}
                stickyOffset={stickyOffset}
            />
        )
    }

    return (
        <div className="relative" style={{ height }} data-attr="release-lane-usage">
            <div className="sticky z-10 flex w-fit flex-col px-3 pt-2" style={{ left: stickyOffset }}>
                <Text size="xs" weight="medium">
                    {CAPTION[target.kind]}
                </Text>
                {usageLoading && !usage ? (
                    <Skeleton className="mt-1 h-3 w-40" />
                ) : !days.length ? (
                    <Text size="xs" variant="muted">
                        {usage ? EMPTY[target.kind] : 'Usage could not load.'}
                    </Text>
                ) : (
                    <Text size="xs" variant="muted" className="tabular-nums">
                        {`Highest: ${humanFriendlyNumber(peak.users)} on ${dayjs(peak.day).format('D MMM')}`}
                    </Text>
                )}
            </div>
            {days.map((day) => {
                const barHeight = peak.users ? Math.max(2, Math.round((day.users / peak.users) * area)) : 0
                const barWidth = Math.max(2, Math.round(scale.day * 0.6))
                const today = dayjs(day.day).isSame(dayjs(), 'day')
                return (
                    <Tooltip key={day.day} trackCursorAxis="x">
                        <TooltipTrigger
                            render={
                                <div
                                    className="absolute rounded-t-[2px] transition-colors hover:brightness-90"
                                    style={{
                                        left: x(day.day, scale) + Math.round((scale.day - barWidth) / 2),
                                        width: barWidth,
                                        bottom: FOOTER,
                                        height: barHeight,
                                        backgroundColor: `color-mix(in oklab, ${color} ${today ? 25 : 50}%, transparent)`,
                                    }}
                                />
                            }
                        />
                        <TooltipContent>
                            <span className="tabular-nums">
                                {`${today ? 'Today so far' : dayjs(day.day).format('D MMM')}: ${humanFriendlyNumber(day.users)} ${day.users === 1 ? 'user' : 'users'}, ${humanFriendlyNumber(day.total)} ${day.total === 1 ? 'event' : 'events'}`}
                            </span>
                        </TooltipContent>
                    </Tooltip>
                )
            })}
        </div>
    )
}
