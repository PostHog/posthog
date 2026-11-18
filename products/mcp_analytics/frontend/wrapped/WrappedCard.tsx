import { ComponentType, forwardRef } from 'react'

import { HoggiePngProps } from 'lib/brand/hoggies'
import { cn } from 'lib/utils/css-classes'

import type { WrappedCardKey } from './storyCards'
import { CARD_THEMES } from './wrappedTheme'

export interface WrappedCardProps {
    cardKey: WrappedCardKey
    kicker: string
    children: React.ReactNode
    hoggie?: ComponentType<HoggiePngProps>
}

/** The poster every story card sits on: its ground, a small heading, and a hedgehog in the corner. */
export const WrappedCard = forwardRef<HTMLDivElement, WrappedCardProps>(function WrappedCard(
    { cardKey, kicker, children, hoggie },
    ref
): JSX.Element {
    const theme = CARD_THEMES[cardKey]
    const Hoggie = hoggie ?? theme.hoggie
    return (
        <div
            ref={ref}
            className={cn('MCPWrapped__card', theme.light && 'MCPWrapped__card--light')}
            style={{ background: theme.background }}
            data-attr={`mcp-wrapped-card-${cardKey}`}
        >
            <span className="MCPWrapped__rise font-mono text-xs font-semibold uppercase tracking-wider opacity-80">
                {kicker}
            </span>
            {children}
            <Hoggie className="MCPWrapped__hoggie" loading="eager" />
        </div>
    )
})
