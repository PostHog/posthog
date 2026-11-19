import { colors } from '@posthog/brand/colors'

import type { MCPWrappedSharesCardApi } from '../../generated/api.schemas'
import { formatPercent } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

const SEGMENT_COLORS = [colors.tangerine.core, colors.lemon.core, colors.teal.core, colors['corn-blue'].core]
const OTHER_COLOR = 'rgb(255 255 255 / 35%)'

export interface SharesCardProps {
    cardKey: 'apps' | 'labs'
    card: MCPWrappedSharesCardApi
    kicker: string
    headline: (leader: string, share: string) => string
    footnote?: string
}

/** One share bar with a legend, for the apps and AI labs cards. */
export function SharesCard({ cardKey, card, kicker, headline, footnote }: SharesCardProps): JSX.Element {
    const [leader] = card.shares
    return (
        <WrappedCard cardKey={cardKey} kicker={kicker}>
            {leader && (
                <h2 className="MCPWrapped__rise m-0 text-4xl font-bold leading-tight">
                    {headline(leader.name, formatPercent(leader.share))}
                </h2>
            )}
            <div className="MCPWrapped__rise flex h-11 gap-0.5 overflow-hidden rounded-xl">
                {card.shares.map((share, index) => (
                    <span
                        key={share.name}
                        className="block h-full"
                        style={{
                            flexGrow: share.share,
                            background:
                                share.name === 'Other' ? OTHER_COLOR : SEGMENT_COLORS[index % SEGMENT_COLORS.length],
                        }}
                    />
                ))}
            </div>
            <ul className="MCPWrapped__rise m-0 grid list-none grid-cols-2 gap-x-3 gap-y-1.5 p-0 text-sm">
                {card.shares.map((share, index) => (
                    <li key={share.name} className="flex items-center gap-1.5">
                        <span
                            className="size-2.5 shrink-0 rounded-sm"
                            style={{
                                background:
                                    share.name === 'Other'
                                        ? OTHER_COLOR
                                        : SEGMENT_COLORS[index % SEGMENT_COLORS.length],
                            }}
                        />
                        {share.name} · {formatPercent(share.share)}
                    </li>
                ))}
            </ul>
            {footnote && <p className="MCPWrapped__rise m-0 text-sm opacity-75">{footnote}</p>}
        </WrappedCard>
    )
}
