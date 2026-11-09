import { Children, type ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

// Falls back to one column when a card in the pair is hidden.
export function TwoColumns({ children }: { children: ReactNode }): JSX.Element | null {
    const cards = Children.toArray(children)
    if (cards.length === 0) {
        return null
    }
    return (
        <div
            className={cn(
                'grid min-w-0 grid-cols-1 gap-4',
                cards.length > 1 && '@min-[64rem]/mcp-overview:grid-cols-2'
            )}
        >
            {cards}
        </div>
    )
}
