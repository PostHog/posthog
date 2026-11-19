import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPWrappedTopToolsCardApi } from '../../generated/api.schemas'
import { formatPercent } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

export function TopToolsCard({
    card,
    totalCalls,
}: {
    card: MCPWrappedTopToolsCardApi
    totalCalls: number
}): JSX.Element {
    const [top] = card.tools
    const busiest = top?.calls ?? 1
    return (
        <WrappedCard cardKey="top_tools" kicker="Your most-called tool">
            {top && (
                <>
                    <div className="MCPWrapped__pop break-all font-mono text-4xl font-bold leading-tight">
                        {top.tool}
                    </div>
                    <p className="MCPWrapped__rise m-0 text-base">
                        <strong className="block">Agents reached for it {humanFriendlyNumber(top.calls)} times.</strong>
                        That's {formatPercent(top.calls / totalCalls)} of all tool calls.
                    </p>
                </>
            )}
            <ol className="m-0 mt-2 flex list-none flex-col gap-3 p-0">
                {card.tools.map((tool, index) => (
                    <li
                        key={tool.tool}
                        className="MCPWrapped__rise grid grid-cols-[1.25rem_1fr_auto] items-center gap-x-2 gap-y-1.5 text-sm tabular-nums"
                        style={{ animationDelay: `${index * 80}ms` }}
                    >
                        <span className="font-bold">{index + 1}</span>
                        <span className="truncate font-mono">{tool.tool}</span>
                        <span>{humanFriendlyNumber(tool.calls)}</span>
                        <span className="col-span-2 col-start-2 h-3 overflow-hidden rounded-full bg-white/20">
                            <span
                                className={cn(
                                    'MCPWrapped__grow-x block h-full rounded-full',
                                    index === 0 ? 'bg-white' : 'bg-white/60'
                                )}
                                style={{
                                    width: `${Math.max(2, (tool.calls / busiest) * 100)}%`,
                                    animationDelay: `${index * 80}ms`,
                                }}
                            />
                        </span>
                    </li>
                ))}
            </ol>
        </WrappedCard>
    )
}
