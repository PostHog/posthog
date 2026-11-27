import { IconBolt, IconHourglass } from '@posthog/icons'

import type { MCPWrappedSpeedCardApi } from '../../generated/api.schemas'
import { durationParts, formatDuration, speedLine, speedTier } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { SPEED_THEMES } from '../wrappedTheme'
import { ToolAward } from './ToolAward'

export function SpeedCard({ card }: { card: MCPWrappedSpeedCardApi }): JSX.Element {
    const { quickest_busy_tool: fastest, slowest_tool: slowest } = card
    const headline = durationParts(card.p95_duration_ms)
    return (
        <WrappedCard cardKey="speed" kicker="Response times" theme={SPEED_THEMES[speedTier(card.p95_duration_ms)]}>
            <div className="MCPWrapped__pop flex flex-wrap items-baseline gap-x-2">
                <span className="text-6xl font-bold leading-none tabular-nums">{headline.value}</span>
                <span className="text-2xl font-bold">{headline.longUnit}</span>
            </div>
            <p className="MCPWrapped__rise m-0 text-base">
                <strong className="block">{speedLine(card.p95_duration_ms)}</strong>
                <span className="MCPWrapped__mark">95%</span> of tool calls came back faster than this.
            </p>
            {(fastest || slowest) && (
                <div className="mt-1 flex flex-col gap-2">
                    {fastest && (
                        <ToolAward
                            label="Speed demon"
                            icon={<IconBolt className="size-3" />}
                            tool={fastest.tool}
                            value={formatDuration(fastest.p95_duration_ms)}
                            unit="p95"
                            detail={`95% of its calls came back in under ${formatDuration(fastest.p95_duration_ms)}.`}
                            tone="good"
                        />
                    )}
                    {slowest && (
                        <ToolAward
                            label="Takes its time"
                            icon={<IconHourglass className="size-3" />}
                            tool={slowest.tool}
                            value={formatDuration(slowest.p95_duration_ms)}
                            unit="p95"
                            detail={`1 in 20 of its calls took longer than ${formatDuration(slowest.p95_duration_ms)}.`}
                            tone="bad"
                        />
                    )}
                </div>
            )}
        </WrappedCard>
    )
}
