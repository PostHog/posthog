import { forwardRef } from 'react'

import { cn } from 'lib/utils/css-classes'

import type { WrappedCardKey } from './storyCards'
import { CARD_THEMES, hoggieReachesEdge, type WrappedCardTheme } from './wrappedTheme'

export interface WrappedCardProps {
    cardKey: WrappedCardKey
    kicker: string
    children: React.ReactNode
    // For a card whose data picks its ground and hedgehog, in place of the card's fixed theme.
    theme?: WrappedCardTheme
    // For a card that shows its own, larger hedgehog instead of the one in the corner.
    hideHoggie?: boolean
}

/** The poster every story card sits on: its ground, a small heading, and a hedgehog in the corner. */
export const WrappedCard = forwardRef<HTMLDivElement, WrappedCardProps>(function WrappedCard(
    { cardKey, kicker, children, theme = CARD_THEMES[cardKey], hideHoggie },
    ref
): JSX.Element {
    const Hoggie = theme.hoggie
    return (
        <div
            ref={ref}
            className="MCPWrapped__card"
            style={{ background: theme.background }}
            data-attr={`mcp-wrapped-card-${cardKey}`}
        >
            <span className="MCPWrapped__rise font-mono text-xs font-semibold uppercase tracking-wider">{kicker}</span>
            {children}
            {!hideHoggie && (
                <Hoggie
                    className={cn('MCPWrapped__hoggie', hoggieReachesEdge(Hoggie) && 'MCPWrapped__hoggie--inset')}
                    loading="eager"
                />
            )}
        </div>
    )
})
