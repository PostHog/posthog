import { colors } from '@posthog/brand/colors'
import { IconStar, IconWarning } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import type { MCPWrappedReliabilityCardApi } from '../../generated/api.schemas'
import { errorLine, formatCallCount, formatPercent, reliabilityLine, toolNameSize } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

// The tiles share one ground, so the badge colour is what tells the good tool from the bad one.
const TONE_COLORS = { good: colors.teal.darker, bad: colors.coral.core } as const

function ToolAward({
    label,
    icon,
    tool,
    value,
    unit,
    detail,
    tone,
}: {
    label: string
    icon: JSX.Element
    tool: string
    value: string
    unit: string
    detail: string
    tone: 'good' | 'bad'
}): JSX.Element {
    return (
        <div className="MCPWrapped__rise flex flex-col gap-1 rounded-xl bg-white/60 px-3 py-2.5">
            <div className="flex items-center gap-1.5 text-xs font-bold">
                <span
                    className="flex size-5 items-center justify-center rounded-full text-white"
                    style={{ background: TONE_COLORS[tone] }}
                >
                    {icon}
                </span>
                {label}
            </div>
            <div className="flex items-end justify-between gap-3">
                <span
                    className={cn(
                        'line-clamp-2 min-w-0 break-all font-mono font-bold',
                        toolNameSize(tool, ['text-base', 'text-sm', 'text-xs'])
                    )}
                    title={tool}
                >
                    {tool}
                </span>
                <span className="shrink-0 text-right leading-none">
                    <span className="block text-xl font-bold tabular-nums">{value}</span>
                    <span className="text-xs opacity-75">{unit}</span>
                </span>
            </div>
            <div className="text-xs opacity-75">{detail}</div>
        </div>
    )
}

export function ReliabilityCard({ card }: { card: MCPWrappedReliabilityCardApi }): JSX.Element {
    const { most_reliable_tool: mvp, struggling_tool: struggling } = card
    return (
        <WrappedCard cardKey="reliability" kicker="Reliability">
            <div className="MCPWrapped__pop flex flex-wrap items-baseline gap-x-2">
                <span className="text-5xl font-bold leading-none tabular-nums">{formatPercent(card.success_rate)}</span>
                <span className="text-xl font-bold">error-free</span>
            </div>
            <p className="MCPWrapped__rise m-0 text-base">
                <strong className="block">{reliabilityLine(card.success_rate)}</strong>
                {errorLine(card.success_rate)}
            </p>
            {(mvp || struggling) && (
                <div className="mt-1 flex flex-col gap-2">
                    {mvp && (
                        <ToolAward
                            label="Your MVP"
                            icon={<IconStar className="size-3" />}
                            tool={mvp.tool}
                            value={formatPercent(1 - mvp.error_rate)}
                            unit="success"
                            tone="good"
                            detail={`Handled ${formatCallCount(mvp.calls)} calls like a champ.`}
                        />
                    )}
                    {struggling && (
                        <ToolAward
                            label="Needs some love"
                            icon={<IconWarning className="size-3" />}
                            tool={struggling.tool}
                            value={formatPercent(struggling.error_rate)}
                            unit="errors"
                            tone="bad"
                            detail={`Had a few rough days across ${formatCallCount(struggling.calls)} calls.`}
                        />
                    )}
                </div>
            )}
        </WrappedCard>
    )
}
