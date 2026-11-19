import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPWrappedToolCallsCardApi } from '../../generated/api.schemas'
import { chartMonths, formatCallCount, formatCompact, formatMonth } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

export function ToolCallsCard({ card }: { card: MCPWrappedToolCallsCardApi }): JSX.Element {
    const months = chartMonths(card.months)
    const busiest = Math.max(...months.map((month) => month.calls))
    const busiestMonth = months.find((month) => month.calls === busiest)
    return (
        <WrappedCard cardKey="tool_calls" kicker="Agents called your tools">
            <div className="MCPWrapped__pop flex flex-wrap items-baseline gap-x-2">
                <span
                    className="text-6xl font-bold leading-none tabular-nums"
                    title={`${card.total_calls.toLocaleString('en-US')} calls`}
                >
                    {formatCallCount(card.total_calls)}
                </span>
                <span className="text-2xl font-bold">times</span>
            </div>
            {busiestMonth && (
                <p className="MCPWrapped__rise m-0 text-base">
                    <strong className="block">{formatMonth(busiestMonth.month)} took the crown.</strong>
                    {humanFriendlyNumber(busiestMonth.calls)} tool calls in a single month.
                    {card.growth_multiple !== null &&
                        ` Calls grew ${card.growth_multiple}× since ${formatMonth(card.months[1]?.month ?? card.months[0].month)}.`}
                </p>
            )}
            <ol className="m-0 mt-2 flex list-none flex-col gap-2 p-0" aria-label="Tool calls by month">
                {months.map((month, index) => (
                    <li
                        key={month.month}
                        className="MCPWrapped__rise grid grid-cols-[2.25rem_1fr_3rem] items-center gap-2 text-sm tabular-nums"
                        style={{ animationDelay: `${index * 80}ms` }}
                    >
                        <span>{formatMonth(month.month, 'short')}</span>
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
                        <span className="text-right">{formatCompact(month.calls)}</span>
                    </li>
                ))}
            </ol>
        </WrappedCard>
    )
}
