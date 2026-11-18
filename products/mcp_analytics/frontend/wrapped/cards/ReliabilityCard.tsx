import type { MCPWrappedReliabilityCardApi } from '../../generated/api.schemas'
import { formatPercent } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

export function ReliabilityCard({ card }: { card: MCPWrappedReliabilityCardApi }): JSX.Element {
    return (
        <WrappedCard cardKey="reliability" kicker="It held up">
            <div className="MCPWrapped__pop text-6xl font-bold leading-none">{formatPercent(card.success_rate)}</div>
            <p className="MCPWrapped__rise m-0 text-base">of calls came back without an error.</p>
            {card.struggling_tool && (
                <div className="MCPWrapped__rise grid grid-cols-2 gap-2.5">
                    <div className="rounded-xl bg-white/45 p-2.5">
                        <div className="font-mono text-[10px] font-semibold uppercase opacity-75">
                            Tool with most errors
                        </div>
                        <div className="break-all font-mono text-base font-bold">{card.struggling_tool.tool}</div>
                    </div>
                    <div className="rounded-xl bg-white/45 p-2.5">
                        <div className="font-mono text-[10px] font-semibold uppercase opacity-75">Error rate</div>
                        <div className="text-xl font-bold">{formatPercent(card.struggling_tool.error_rate)}</div>
                    </div>
                </div>
            )}
        </WrappedCard>
    )
}
