import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPWrappedToolCallsCardApi } from '../../generated/api.schemas'
import { formatMonth } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

export function ToolCallsCard({ card }: { card: MCPWrappedToolCallsCardApi }): JSX.Element {
    const busiest = Math.max(...card.months.map((month) => month.calls))
    const busiestMonth = card.months.find((month) => month.calls === busiest)
    return (
        <WrappedCard cardKey="tool_calls" kicker="Agents called your tools">
            <div className="MCPWrapped__pop text-6xl font-bold leading-none tabular-nums">
                {card.total_calls.toLocaleString('en-US')}
            </div>
            <p className="MCPWrapped__rise m-0 text-base">times this year.</p>
            <div className="MCPWrapped__rise flex h-20 items-end gap-1.5">
                {card.months.map((month) => (
                    <div key={month.month} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
                        <div
                            className="w-full rounded-t bg-white/85"
                            style={{ height: `${Math.max(4, (month.calls / busiest) * 100)}%` }}
                            title={`${humanFriendlyNumber(month.calls)} calls`}
                        />
                        <span className="font-mono text-[10px] font-semibold">{formatMonth(month.month, 'short')}</span>
                    </div>
                ))}
            </div>
            <div className="MCPWrapped__rise flex flex-wrap gap-1.5">
                {card.growth_multiple !== null && (
                    <span className="rounded-full bg-white/20 px-2 py-0.5 font-mono text-xs font-semibold">
                        {card.growth_multiple}× since {formatMonth(card.months[1]?.month ?? card.months[0].month)}
                    </span>
                )}
                {busiestMonth && (
                    <span className="rounded-full bg-white/20 px-2 py-0.5 font-mono text-xs font-semibold">
                        Busiest: {formatMonth(busiestMonth.month)}
                    </span>
                )}
            </div>
        </WrappedCard>
    )
}
