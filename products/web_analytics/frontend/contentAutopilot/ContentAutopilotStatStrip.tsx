import { Children } from 'react'

import { cn } from '@posthog/quill'

// The border color shows through the 1px gaps, so cells are divided on every row and column at any width.
// Each cell takes bg-card itself, because quill's scoped utilities have no child variant.
export const ContentAutopilotStatStrip = ({
    children,
    className,
    'data-attr': dataAttr,
}: {
    children: React.ReactNode
    className: string
    'data-attr': string
}): JSX.Element => (
    <div
        className={cn('grid gap-px overflow-hidden rounded-lg border border-border bg-border', className)}
        data-attr={dataAttr}
    >
        {Children.map(children, (child) => (child ? <div className="min-w-0 bg-card">{child}</div> : null))}
    </div>
)
