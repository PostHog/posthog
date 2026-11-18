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
            <div className="MCPWrapped__rise mt-4 flex h-36 items-end gap-1.5" aria-label="Tool calls by month">
                {months.map((month, index) => (
                    <div key={month.month} className="flex h-full min-w-0 max-w-12 flex-1 flex-col items-center gap-1">
                        <div className="flex w-full flex-1 flex-col items-center justify-end gap-1">
                            <span className="font-mono text-[10px] font-semibold leading-none">
                                {formatCompact(month.calls)}
                            </span>
                            <div
                                className={cn(
                                    'MCPWrapped__grow w-full rounded-t',
                                    month.calls === busiest ? 'bg-warning' : 'bg-white/85'
                                )}
                                style={{
                                    height: `${Math.max(4, (month.calls / busiest) * 100)}%`,
                                    animationDelay: `${index * 80}ms`,
                                }}
                                title={`${humanFriendlyNumber(month.calls)} calls`}
                            />
                        </div>
                        <span className="font-mono text-[10px] font-semibold">{formatMonth(month.month, 'short')}</span>
                    </div>
                ))}
            </div>
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
