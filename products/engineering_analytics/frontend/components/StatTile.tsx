import { ReactNode } from 'react'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'

/** Plain headline metric tile. For the clickable filter-toggle variant, use StatCard. */
export function StatTile({
    label,
    value,
    sub,
    className,
}: {
    label: string
    value: string
    sub: ReactNode
    className?: string
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className={cn('flex min-w-44 flex-1 flex-col gap-1 px-5 py-4', className)}>
            <span className="text-xs text-secondary">{label}</span>
            <span className="text-2xl font-semibold leading-none tabular-nums">{value}</span>
            <span className="text-xs text-tertiary">{sub}</span>
        </LemonCard>
    )
}
