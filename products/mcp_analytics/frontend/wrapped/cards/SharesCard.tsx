import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { cn } from 'lib/utils/css-classes'

import { labMark, type ModelLab } from '../../aiLabs'
import { HarnessLogo } from '../../dashboard/harness'
import type { MCPWrappedSharesCardApi } from '../../generated/api.schemas'
import { formatPercent } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

const OTHER = 'Other'

export interface SharesCardProps {
    cardKey: 'apps' | 'labs'
    card: MCPWrappedSharesCardApi
    kicker: string
    headline: (leader: string, share: string) => string
    otherLabel: string
}

function Logo({
    cardKey,
    name,
    className,
}: {
    cardKey: 'apps' | 'labs'
    name: string
    className: string
}): JSX.Element {
    return cardKey === 'apps' ? (
        <HarnessLogo category={name} className={className} />
    ) : (
        <BrandMark name={labMark(name as ModelLab) ?? 'Unbranded model'} className={className} />
    )
}

/** The apps or AI labs that made the calls, ranked, with each one's logo. */
export function SharesCard({ cardKey, card, kicker, headline, otherLabel }: SharesCardProps): JSX.Element {
    const named = card.shares.filter((share) => share.name !== OTHER)
    const other = card.shares.find((share) => share.name === OTHER)
    const [leader] = named
    return (
        <WrappedCard cardKey={cardKey} kicker={kicker}>
            {leader && (
                <>
                    <div className="MCPWrapped__pop flex size-16 items-center justify-center rounded-2xl bg-white text-black shadow-lg">
                        <Logo cardKey={cardKey} name={leader.name} className="size-9" />
                    </div>
                    <h2 className="MCPWrapped__rise m-0 text-4xl font-bold leading-tight">
                        {headline(leader.name, formatPercent(leader.share))}
                    </h2>
                </>
            )}
            <ol className="m-0 mt-2 flex list-none flex-col gap-3 p-0">
                {named.map((share, index) => (
                    <li
                        key={share.name}
                        className="MCPWrapped__rise grid grid-cols-[1.75rem_1fr_auto] items-center gap-x-2 gap-y-1.5 text-sm tabular-nums"
                        style={{ animationDelay: `${index * 80}ms` }}
                    >
                        <span className="flex size-7 items-center justify-center rounded-full bg-white text-black">
                            <Logo cardKey={cardKey} name={share.name} className="size-4" />
                        </span>
                        <span className="truncate">{share.name}</span>
                        <span>{formatPercent(share.share)}</span>
                        <span className="col-span-2 col-start-2 h-3 overflow-hidden rounded-full bg-white/20">
                            <span
                                className={cn(
                                    'MCPWrapped__grow-x block h-full rounded-full',
                                    index === 0 ? 'bg-white' : 'bg-white/60'
                                )}
                                style={{
                                    width: `${Math.max(2, (share.share / leader.share) * 100)}%`,
                                    animationDelay: `${index * 80}ms`,
                                }}
                            />
                        </span>
                    </li>
                ))}
            </ol>
            {other && (
                <p className="MCPWrapped__rise m-0 text-sm opacity-75">
                    {otherLabel}: {formatPercent(other.share)}
                </p>
            )}
        </WrappedCard>
    )
}
