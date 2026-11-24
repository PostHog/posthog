import { IconWarning } from '@posthog/icons'

import type { MCPWrappedReliabilityCardApi } from '../../generated/api.schemas'
import { formatPercent, formatSuccessRate, reliabilityLine } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

export function ReliabilityCard({ card }: { card: MCPWrappedReliabilityCardApi }): JSX.Element {
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
                That's the share of tool calls that returned without an error.
            </p>
            {card.struggling_tool && (
                <div className="MCPWrapped__rise flex items-center gap-3 rounded-xl bg-black/10 p-3">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-black/80 text-white">
                        <IconWarning className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                        <div className="text-sm opacity-75">Needs the most attention</div>
                        <div className="truncate font-mono font-bold">{card.struggling_tool.tool}</div>
                    </div>
                    <div className="shrink-0 text-right">
                        <div className="font-bold tabular-nums">{formatPercent(card.struggling_tool.error_rate)}</div>
                        <div className="text-sm opacity-75">failed</div>
                    </div>
                </div>
            )}
        </WrappedCard>
    )
}
