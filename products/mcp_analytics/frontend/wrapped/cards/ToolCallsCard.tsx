import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPWrappedToolCallsCardApi } from '../../generated/api.schemas'
import { chartMonths, formatCompact, formatMonth, headlineNumberSize } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

export function ToolCallsCard({ card }: { card: MCPWrappedToolCallsCardApi }): JSX.Element {
    const months = chartMonths(card.months)
    const busiest = Math.max(...months.map((month) => month.calls))
    const total = card.total_calls.toLocaleString('en-US')
    return (
        <WrappedCard cardKey="tool_calls" kicker="This year, AI agents called your tools">
            <div className="MCPWrapped__pop flex flex-wrap items-baseline gap-x-2">
                <span className={cn('font-bold leading-none tabular-nums', headlineNumberSize(total))}>{total}</span>
                <span className="text-2xl font-semibold">times</span>
            </div>
            <ol className="m-0 mt-2 flex list-none flex-col gap-2 p-0" aria-label="Tool calls by month">
                {months.map((month, index) => (
                    <li
                        key={month.month}
                        className="MCPWrapped__rise grid grid-cols-[2.25rem_1fr_3rem] items-center gap-2"
                        style={{ animationDelay: `${index * 80}ms` }}
                    >
                        <span className="font-mono text-xs font-semibold">{formatMonth(month.month, 'short')}</span>
                        <span className="h-3 overflow-hidden rounded-full bg-white/20">
                            <span
                                className={cn(
                                    'MCPWrapped__grow-x block h-full rounded-full',
                                    month.calls === busiest ? 'bg-warning' : 'bg-white/85'
                                )}
                                style={{
                                    width: `${Math.max(2, (month.calls / busiest) * 100)}%`,
                                    animationDelay: `${index * 80}ms`,
                                }}
                                title={`${humanFriendlyNumber(month.calls)} calls`}
                            />
                        </span>
                        <span className="text-right font-mono text-xs font-semibold">{formatCompact(month.calls)}</span>
                    </li>
                ))}
            </ol>
            {card.growth_multiple !== null && (
                <div className="MCPWrapped__rise flex">
                    <span className="rounded-full bg-white/20 px-2 py-0.5 font-mono text-xs font-semibold">
                        {card.growth_multiple}× since {formatMonth(card.months[1]?.month ?? card.months[0].month)}
                    </span>
                </div>
            )}
        </WrappedCard>
    )
}
