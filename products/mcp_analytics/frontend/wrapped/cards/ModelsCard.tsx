import { cn } from 'lib/utils/css-classes'

import type { MCPWrappedSharesCardApi } from '../../generated/api.schemas'
import { formatPercent } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

export function ModelsCard({ card }: { card: MCPWrappedSharesCardApi }): JSX.Element {
    const families = card.shares.filter((share) => share.name !== 'Other')
    const [leader] = families
    return (
        <WrappedCard cardKey="models" kicker="The models doing the calling">
            {leader && (
                <>
                    <h2 className="MCPWrapped__pop m-0 text-4xl font-bold leading-tight">{leader.name}</h2>
                    <p className="MCPWrapped__rise m-0 text-base">
                        was the top model family, behind {formatPercent(leader.share)} of calls that named a model.
                    </p>
                </>
            )}
            <ol className="m-0 mt-2 flex list-none flex-col gap-3 p-0">
                {families.map((family, index) => (
                    <li
                        key={family.name}
                        className="MCPWrapped__rise grid grid-cols-[1.25rem_1fr_auto] items-center gap-x-2 gap-y-1.5 text-sm tabular-nums"
                        style={{ animationDelay: `${index * 80}ms` }}
                    >
                        <span className="font-bold">{index + 1}</span>
                        <span className="truncate">{family.name}</span>
                        <span>{formatPercent(family.share)}</span>
                        <span className="col-span-2 col-start-2 h-3 overflow-hidden rounded-full bg-white/20">
                            <span
                                className={cn(
                                    'MCPWrapped__grow-x block h-full rounded-full',
                                    index === 0 ? 'bg-white' : 'bg-white/60'
                                )}
                                style={{
                                    width: `${Math.max(2, (family.share / leader.share) * 100)}%`,
                                    animationDelay: `${index * 80}ms`,
                                }}
                            />
                        </span>
                    </li>
                ))}
            </ol>
            <p className="MCPWrapped__rise m-0 text-sm opacity-75">
                Grouped by model family, as each agent reported it.
            </p>
        </WrappedCard>
    )
}
