import { cn } from 'lib/utils/css-classes'

import type { MCPWrappedTopToolsCardApi } from '../../generated/api.schemas'
import { formatCallCount, formatPercent, toolNameSize } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { StoryBar } from './StoryBar'

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
                    <div
                        className={cn(
                            'MCPWrapped__pop break-all font-mono font-bold leading-tight',
                            toolNameSize(top.tool, ['text-4xl', 'text-3xl', 'text-2xl'])
                        )}
                    >
                        {top.tool}
                    </div>
                    <p className="MCPWrapped__rise m-0 text-base">
                        <strong className="block">
                            Agents reached for it <span className="MCPWrapped__mark">{formatCallCount(top.calls)}</span>{' '}
                            times.
                        </strong>
                        That's {formatPercent(top.calls / totalCalls)} of all tool calls.
                    </p>
                </>
            )}
            <ol className="m-0 mt-2 flex list-none flex-col gap-2 p-0" aria-label="Most-called tools">
                {card.tools.map((tool, index) => (
                    <StoryBar
                        key={tool.tool}
                        index={index}
                        label={
                            <>
                                <span className="w-3 shrink-0">{index + 1}</span>
                                <span className="truncate font-mono">{tool.tool}</span>
                            </>
                        }
                        value={formatCallCount(tool.calls)}
                        fraction={tool.calls / busiest}
                        emphasized={index === 0}
                        title={`${tool.tool}: ${tool.calls.toLocaleString('en-US')} calls`}
                    />
                ))}
            </ol>
        </WrappedCard>
    )
}
