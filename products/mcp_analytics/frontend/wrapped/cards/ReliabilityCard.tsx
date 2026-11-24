import { cn } from 'lib/utils/css-classes'

import type { MCPWrappedReliabilityCardApi } from '../../generated/api.schemas'
import { formatPercent, formatSuccessRate } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

const DOTS = 100

export function ReliabilityCard({ card }: { card: MCPWrappedReliabilityCardApi }): JSX.Element {
    const cleanDots = Math.round(card.success_rate * DOTS)
    return (
        <WrappedCard cardKey="reliability" kicker="Reliability">
            <div className="MCPWrapped__pop text-6xl font-bold leading-none tabular-nums">
                {formatSuccessRate(card.success_rate)}
            </div>
            <p className="MCPWrapped__rise m-0 text-base">of tool calls returned without an error.</p>
            <div className="MCPWrapped__rise flex flex-col gap-1.5">
                <div className="grid grid-cols-[repeat(20,minmax(0,1fr))] gap-1" aria-hidden>
                    {Array.from({ length: DOTS }, (_, index) => (
                        <span
                            key={index}
                            className={cn('aspect-square rounded-full', index < cleanDots ? 'bg-white' : 'bg-black/70')}
                        />
                    ))}
                </div>
                <span className="text-xs opacity-75">Each dot is 1% of calls.</span>
            </div>
            {card.struggling_tool && (
                <div className="MCPWrapped__rise flex flex-col gap-0.5 rounded-xl bg-white/45 p-3">
                    <span className="text-sm opacity-75">Needs the most attention</span>
                    <span className="break-all font-mono font-bold">{card.struggling_tool.tool}</span>
                    <span className="text-sm">
                        {formatPercent(card.struggling_tool.error_rate)} of its calls failed.
                    </span>
                </div>
            )}
        </WrappedCard>
    )
}
