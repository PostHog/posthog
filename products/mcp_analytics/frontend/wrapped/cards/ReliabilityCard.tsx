import { IconWarning } from '@posthog/icons'

import type { MCPWrappedReliabilityCardApi } from '../../generated/api.schemas'
import { errorLine, formatPercent, formatSuccessRate, reliabilityLine } from '../storyCards'
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
                {errorLine(card.success_rate)}
            </p>
            {card.struggling_tool && (
                <div className="MCPWrapped__rise flex items-center gap-3 rounded-xl bg-black/10 p-3">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-black/80 text-white">
                        <IconWarning className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                        <div className="text-sm opacity-75">Most errors</div>
                        <div className="truncate font-mono font-bold">{card.struggling_tool.tool}</div>
                    </div>
                    <div className="shrink-0 text-right">
                        <div className="font-bold tabular-nums">{formatPercent(card.struggling_tool.error_rate)}</div>
                        <div className="text-sm opacity-75">error rate</div>
                    </div>
                </div>
            )}
            {card.struggling_tool && (
                <p className="MCPWrapped__rise absolute bottom-10 left-6 m-0 max-w-[50%] rounded-xl rounded-br-none bg-white/60 px-3 py-2 text-sm font-bold">
                    Even superheroes have bad days.
                </p>
            )}
        </WrappedCard>
    )
}
