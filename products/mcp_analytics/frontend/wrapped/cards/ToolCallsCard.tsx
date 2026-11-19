import { colors } from '@posthog/brand/colors'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPWrappedToolCallsCardApi } from '../../generated/api.schemas'
import { chartMonths, formatCallCount, formatCompact, formatMonth } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

function Crown(): JSX.Element {
    return (
        <svg viewBox="0 0 24 20" className="size-4 shrink-0 drop-shadow" role="img" aria-label="Busiest month">
            <g fill={colors.lemon.core} stroke="rgb(0 0 0 / 30%)" strokeWidth="1" strokeLinejoin="round">
                <path d="M3 7l4.5 4.5L12 4l4.5 7.5L21 7l-1.8 9.5H4.8z" />
                <rect x="4.8" y="16.5" width="14.4" height="2.5" rx="1" />
                <circle cx="3" cy="6" r="1.7" />
                <circle cx="12" cy="3" r="1.7" />
                <circle cx="21" cy="6" r="1.7" />
            </g>
        </svg>
    )
}

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
                        className="MCPWrapped__rise grid grid-cols-[3rem_1fr_3rem] items-center gap-2 text-sm tabular-nums"
                        style={{ animationDelay: `${index * 80}ms` }}
                    >
                        <span className="flex items-center gap-1">
                            {formatMonth(month.month, 'short')}
                            {month.calls === busiest && <Crown />}
                        </span>
                        <span className="h-3 overflow-hidden rounded-full bg-white/20">
                            <span
                                className={cn(
                                    'MCPWrapped__grow-x block h-full rounded-full',
                                    month.calls === busiest ? 'bg-white' : 'bg-white/60'
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
