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
            <ol className="m-0 flex list-none flex-col gap-2.5 p-0">
                {families.map((family, index) => (
                    <li
                        key={family.name}
                        className="MCPWrapped__rise grid grid-cols-[1.25rem_1fr_auto] items-center gap-2 text-sm tabular-nums"
                    >
                        <span className="font-bold">{index + 1}</span>
                        <span className="truncate">{family.name}</span>
                        <span>{formatPercent(family.share)}</span>
                        <span className="col-span-2 col-start-2 h-1.5 overflow-hidden rounded bg-white/20">
                            <span
                                className={
                                    index === 0 ? 'block h-full rounded bg-warning' : 'block h-full rounded bg-white'
                                }
                                style={{ width: `${(family.share / leader.share) * 100}%` }}
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
