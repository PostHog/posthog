import { IconStar, IconWarning } from '@posthog/icons'

import type { MCPWrappedReliabilityCardApi } from '../../generated/api.schemas'
import { errorLine, formatCallCount, formatPercent, reliabilityLine } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { ToolAward } from './ToolAward'

export function ReliabilityCard({ card }: { card: MCPWrappedReliabilityCardApi }): JSX.Element {
    const { most_reliable_tool: mvp, struggling_tool: struggling } = card
    return (
        <WrappedCard cardKey="reliability" kicker="Reliability">
            <div className="MCPWrapped__pop flex flex-wrap items-baseline gap-x-2">
                <span className="text-5xl font-bold leading-none tabular-nums">{formatPercent(card.success_rate)}</span>
                <span className="text-xl font-bold">error-free</span>
            </div>
            <p className="MCPWrapped__rise m-0 text-base">
                <strong className="block">{reliabilityLine(card.success_rate)}</strong>
                {errorLine(card.success_rate)}
            </p>
            {(mvp || struggling) && (
                <div className="mt-1 flex flex-col gap-2">
                    {mvp && (
                        <ToolAward
                            label="Your MVP"
                            icon={<IconStar className="size-3" />}
                            tool={mvp.tool}
                            value={formatPercent(1 - mvp.error_rate)}
                            unit="success"
                            tone="good"
                            detail={`Handled ${formatCallCount(mvp.calls)} calls like a champ.`}
                        />
                    )}
                    {struggling && (
                        <ToolAward
                            label="Needs some love"
                            icon={<IconWarning className="size-3" />}
                            tool={struggling.tool}
                            value={formatPercent(struggling.error_rate)}
                            unit="errors"
                            tone="bad"
                            detail={`Had a few rough days across ${formatCallCount(struggling.calls)} calls.`}
                        />
                    )}
                </div>
            )}
        </WrappedCard>
    )
}
