import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPWrappedToolCallsCardApi } from '../../generated/api.schemas'
import { formatCompact, formatMonth, yearMonths } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

export function ToolCallsCard({ card }: { card: MCPWrappedToolCallsCardApi }): JSX.Element {
    const months = yearMonths(card.months)
    const busiest = Math.max(...card.months.map((month) => month.calls))
    return (
        <WrappedCard cardKey="tool_calls" kicker="AI agents called your tools">
            <div className="MCPWrapped__pop text-6xl font-bold leading-none tabular-nums">
                {card.total_calls.toLocaleString('en-US')}
            </div>
            <p className="MCPWrapped__rise m-0 text-base">times this year.</p>
            <div className="MCPWrapped__rise mt-2 flex h-36 items-end gap-1" aria-label="Tool calls by month">
                {months.map((month, index) => {
                    const tracked = month.calls !== null
                    const isBusiest = month.calls === busiest
                    return (
                        <div key={month.month} className="flex h-full min-w-0 flex-1 flex-col items-center gap-1">
                            <div className="flex w-full flex-1 flex-col items-center justify-end gap-1">
                                {tracked && (
                                    <span className="font-mono text-[9px] font-semibold leading-none">
                                        {formatCompact(month.calls ?? 0)}
                                    </span>
                                )}
                                <div
                                    className={cn(
                                        'w-full rounded-t',
                                        tracked && 'MCPWrapped__grow',
                                        !tracked ? 'bg-white/20' : isBusiest ? 'bg-warning' : 'bg-white/85'
                                    )}
                                    style={{
                                        height: tracked ? `${Math.max(4, ((month.calls ?? 0) / busiest) * 100)}%` : 3,
                                        animationDelay: `${index * 60}ms`,
                                    }}
                                    title={tracked ? `${humanFriendlyNumber(month.calls)} calls` : 'Not tracked yet'}
                                />
                            </div>
                            <span className={cn('font-mono text-[9px] font-semibold', !tracked && 'opacity-60')}>
                                {formatMonth(month.month, 'short').charAt(0)}
                            </span>
                        </div>
                    )
                })}
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
