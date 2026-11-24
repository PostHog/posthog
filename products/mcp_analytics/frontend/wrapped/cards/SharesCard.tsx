import { BrandMark } from 'lib/components/BrandMark/BrandMark'

import { labMark, modelLab, type ModelLab } from '../../aiLabs'
import { HarnessLogo } from '../../dashboard/harness'
import type { MCPWrappedSharesCardApi } from '../../generated/api.schemas'
import { formatPercent } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { StoryBar } from './StoryBar'

const OTHER = 'Other'

type SharesCardKey = 'apps' | 'labs' | 'models'

export interface SharesCardProps {
    cardKey: SharesCardKey
    card: MCPWrappedSharesCardApi
    kicker: string
    headline: (leader: string, share: string) => string
    otherLabel: string
}

function Logo({ cardKey, name, className }: { cardKey: SharesCardKey; name: string; className: string }): JSX.Element {
    if (cardKey === 'apps') {
        return <HarnessLogo category={name} className={className} />
    }
    const lab = cardKey === 'models' ? modelLab(name) : (name as ModelLab)
    return <BrandMark name={labMark(lab) ?? 'Unbranded model'} className={className} />
}

/** The apps, AI labs or model families behind the calls, ranked, with each one's logo. */
export function SharesCard({ cardKey, card, kicker, headline, otherLabel }: SharesCardProps): JSX.Element {
    const named = card.shares.filter((share) => share.name !== OTHER)
    const other = card.shares.find((share) => share.name === OTHER)
    const [leader] = named
    const rows = [
        ...named.map((share) => ({ ...share, isOther: false })),
        ...(other ? [{ ...other, isOther: true }] : []),
    ]
    return (
        <WrappedCard cardKey={cardKey} kicker={kicker}>
            {leader && (
                <h2 className="MCPWrapped__rise m-0 text-4xl font-bold leading-tight [overflow-wrap:anywhere]">
                    {headline(leader.name, formatPercent(leader.share))}
                </h2>
            )}
            <ol className="m-0 mt-2 flex list-none flex-col gap-2 p-0">
                {rows.map((row, index) => (
                    <StoryBar
                        key={row.name}
                        index={index}
                        label={
                            <>
                                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-white text-black">
                                    {row.isOther ? (
                                        <BrandMark
                                            name={cardKey === 'apps' ? 'Other harnesses' : 'Unbranded model'}
                                            className="size-3.5"
                                        />
                                    ) : (
                                        <Logo cardKey={cardKey} name={row.name} className="size-3.5" />
                                    )}
                                </span>
                                <span className="truncate">{row.isOther ? otherLabel : row.name}</span>
                            </>
                        }
                        value={formatPercent(row.share)}
                        // Every bar is out of all calls, so the leftover share reads at its true size.
                        fraction={row.share}
                        emphasized={index === 0}
                        muted={row.isOther}
                        title={row.isOther ? otherLabel : row.name}
                    />
                ))}
            </ol>
        </WrappedCard>
    )
}
