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
                <div className="MCPWrapped__rise mt-2 flex flex-col gap-2">
                    <span className="text-sm opacity-75">The tool with the most errors</span>
                    <div className="grid grid-cols-[1.75rem_1fr_auto] items-center gap-x-2 gap-y-1.5 text-sm tabular-nums">
                        <span className="row-span-2 flex size-7 items-center justify-center self-center rounded-full bg-white">
                            <IconWarning className="size-4" />
                        </span>
                        <span className="truncate font-mono font-bold">{card.struggling_tool.tool}</span>
                        <span>{formatPercent(card.struggling_tool.error_rate)} errors</span>
                        <span className="col-span-2 col-start-2 row-start-2 h-3 overflow-hidden rounded-full bg-black/10">
                            <span
                                className="MCPWrapped__grow-x block h-full rounded-full bg-black/70"
                                style={{ width: `${Math.max(2, card.struggling_tool.error_rate * 100)}%` }}
                            />
                        </span>
                    </div>
                </div>
            )}
        </WrappedCard>
    )
}
