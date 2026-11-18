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
                    <div className="MCPWrapped__pop break-all font-mono text-3xl font-bold">{top.tool}</div>
                    <p className="MCPWrapped__rise m-0 text-base">
                        {humanFriendlyNumber(top.calls)} calls, {formatPercent(top.calls / totalCalls)} of all tool
                        calls.
                    </p>
                </>
            )}
            <ol className="m-0 flex list-none flex-col gap-2.5 p-0">
                {card.tools.map((tool, index) => (
                    <li
                        key={tool.tool}
                        className="MCPWrapped__rise grid grid-cols-[1.25rem_1fr_auto] items-center gap-2"
                    >
                        <span className="text-lg font-bold">{index + 1}</span>
                        <span className="truncate font-mono text-sm">{tool.tool}</span>
                        <span className="text-sm">{humanFriendlyNumber(tool.calls)}</span>
                        <span className="col-span-2 col-start-2 h-1.5 overflow-hidden rounded bg-white/20">
                            <span
                                className={
                                    index === 0 ? 'block h-full rounded bg-warning' : 'block h-full rounded bg-white'
                                }
                                style={{ width: `${(tool.calls / busiest) * 100}%` }}
                            />
                        </span>
                    </li>
                ))}
            </ol>
        </WrappedCard>
    )
}
