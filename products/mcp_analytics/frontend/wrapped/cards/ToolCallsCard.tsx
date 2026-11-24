import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPWrappedToolCallsCardApi } from '../../generated/api.schemas'
import { chartMonths, formatCallCount, formatCompact, formatMonth } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { StoryBar } from './StoryBar'

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
                    <strong className="block">{formatMonth(busiestMonth.month)} was wild!</strong>
                    You handled <span className="MCPWrapped__mark">{formatCallCount(busiestMonth.calls)}</span> tool
                    calls.
                    {card.growth_multiple !== null &&
                        ` Calls grew ${card.growth_multiple}× since ${formatMonth(card.months[1]?.month ?? card.months[0].month)}.`}
                </p>
            )}
            {/* Fewer months get thicker bars, so a short year still fills the card and a long one still fits. */}
            <ol className="m-0 mt-2 flex list-none flex-col gap-2 p-0" aria-label="Tool calls by month">
                {months.map((month, index) => (
                    <StoryBar
                        key={month.month}
                        index={index}
                        label={formatMonth(month.month, 'short')}
                        value={formatCompact(month.calls)}
                        fraction={month.calls / busiest}
                        emphasized={month.calls === busiest}
                        size={months.length <= 4 ? 'large' : months.length <= 6 ? 'medium' : 'small'}
                        title={`${humanFriendlyNumber(month.calls)} calls`}
                    />
                ))}
            </ol>
        </WrappedCard>
    )
}
