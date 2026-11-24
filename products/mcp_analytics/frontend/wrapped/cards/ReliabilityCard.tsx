import { IconStar, IconWarning } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import type { MCPWrappedReliabilityCardApi } from '../../generated/api.schemas'
import { errorLine, formatPercent, formatSuccessRate, reliabilityLine } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

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
        <div
            className={cn(
                'MCPWrapped__rise flex flex-col gap-1.5 rounded-2xl px-4 py-3',
                tone === 'good' ? 'bg-white/55' : 'bg-black/10'
            )}
        >
            <div className="flex items-center gap-1.5 text-sm font-bold">
                {icon}
                {label}
            </div>
            <div className="flex items-end justify-between gap-3">
                <span className="min-w-0 truncate font-mono text-xl font-bold">{tool}</span>
                <span className="shrink-0 text-right leading-none">
                    <span className="block text-2xl font-bold tabular-nums">{value}</span>
                    <span className="text-xs opacity-75">{unit}</span>
                </span>
            </div>
            <div className="text-sm opacity-75">{detail}</div>
        </div>
    )
}

export function ReliabilityCard({ card }: { card: MCPWrappedReliabilityCardApi }): JSX.Element {
    const { most_reliable_tool: mvp, struggling_tool: struggling } = card
    return (
        <WrappedCard cardKey="reliability" kicker="Reliability">
            <div className="MCPWrapped__pop flex flex-wrap items-baseline gap-x-2">
                <span className="text-6xl font-bold leading-none tabular-nums">
                    {formatSuccessRate(card.success_rate)}
                </span>
                <span className="text-2xl font-bold">error-free</span>
            </div>
            <p className="MCPWrapped__rise m-0 text-base">
                <strong className="block">{reliabilityLine(card.success_rate)}</strong>
                {errorLine(card.success_rate)}
            </p>
            {(mvp || struggling) && (
                <div className="mt-2 flex flex-col gap-3">
                    {mvp && (
                        <ToolAward
                            label="Your MVP"
                            icon={<IconStar className="size-4" />}
                            tool={mvp.tool}
                            value={formatSuccessRate(1 - mvp.error_rate)}
                            unit="success"
                            tone="good"
                            detail={`Handled ${mvp.calls.toLocaleString('en-US')} calls like a champ.`}
                        />
                    )}
                    {struggling && (
                        <ToolAward
                            label="Needs some love"
                            icon={<IconWarning className="size-4" />}
                            tool={struggling.tool}
                            value={formatPercent(struggling.error_rate)}
                            unit="errors"
                            tone="bad"
                            detail={`Had a few rough days across ${struggling.calls.toLocaleString('en-US')} calls.`}
                        />
                    )}
                </div>
            )}
        </WrappedCard>
    )
}
