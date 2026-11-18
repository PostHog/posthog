import type { MCPWrappedSharesCardApi } from '../../generated/api.schemas'
import { formatPercent } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

export function ModelsCard({ card }: { card: MCPWrappedSharesCardApi }): JSX.Element {
    const families = card.shares.filter((share) => share.name !== 'Other')
    const [leader] = families
    return (
        <WrappedCard cardKey="models" kicker="The models behind the calls">
            {leader && (
                <>
                    <h2 className="MCPWrapped__pop m-0 text-4xl font-bold leading-tight">{leader.name}</h2>
                    <p className="MCPWrapped__rise m-0 text-base">
                        was the most used model family, in {formatPercent(leader.share)} of calls with a model.
                    </p>
                </>
            )}
            <ol className="m-0 flex list-none flex-col gap-2.5 p-0">
                {families.map((family, index) => (
                    <li
                        key={family.name}
                        className="MCPWrapped__rise grid grid-cols-[1.25rem_1fr_auto] items-center gap-2"
                    >
                        <span className="text-lg font-bold">{index + 1}</span>
                        <span className="truncate text-sm">{family.name}</span>
                        <span className="text-sm">{formatPercent(family.share)}</span>
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
            <p className="MCPWrapped__rise m-0 text-xs opacity-75">Model families, as the agents reported them.</p>
        </WrappedCard>
    )
}
