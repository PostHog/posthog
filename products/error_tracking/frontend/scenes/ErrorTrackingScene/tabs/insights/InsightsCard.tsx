import { Card, CardContent, CardDescription, CardHeader, CardTitle } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

/** The card every panel on the insights tab sits in, so the tab reads as one grid of panels. */
export function InsightsCard({
    title,
    description,
    action,
    children,
    className,
    contentClassName,
}: {
    title: string
    description?: string
    /** Rendered in the header's top-right corner, for a single control such as a link out. */
    action?: React.ReactNode
    children: React.ReactNode
    className?: string
    contentClassName?: string
}): JSX.Element {
    return (
        <Card size="sm" className={cn('min-w-0', className)}>
            {/* The header's own layout is a grid built around quill's card-action slot, which this app's
                quill build does not export. Switching it to flex puts the action beside the title
                without reaching for the slot's markup. */}
            <CardHeader className="flex flex-row items-start justify-between gap-2">
                <div className="flex min-w-0 flex-col gap-1">
                    {/* quill renders CardTitle as a plain div, so the panel titles carry no heading
                        semantics on their own. The role restores them without forking the primitive
                        or restating its typography on an inner element. */}
                    <CardTitle role="heading" aria-level={3}>
                        {title}
                    </CardTitle>
                    {description ? <CardDescription>{description}</CardDescription> : null}
                </div>
                {action ? <div className="shrink-0">{action}</div> : null}
            </CardHeader>
            {/* min-h-0 lets a height-constrained card's content shrink instead of overflowing the card's clip. */}
            <CardContent className={cn('flex min-h-0 flex-1 flex-col', contentClassName)}>{children}</CardContent>
        </Card>
    )
}
