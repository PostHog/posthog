import { PropsWithChildren } from 'react'

import { cn } from 'lib/utils/css-classes'

const SHARED_STYLES =
    'flex items-stretch [&_.LemonInput]:border-0 [&_.LemonInput]:rounded-none [&_.LemonInput]:shadow-none [&_.LemonInput]:bg-transparent [&_.LemonButton]:rounded-none [&_.LemonButton:not(:hover)]:bg-transparent'

const VARIANT_STYLES = {
    pill: 'rounded-full border border-[var(--color-border-primary)] bg-[var(--color-bg-fill-input)]',
    embedded: 'bg-transparent',
} as const

export const SearchBar = ({
    variant = 'pill',
    children,
    className,
}: PropsWithChildren<{
    variant?: 'pill' | 'embedded'
    className?: string
}>): JSX.Element => <div className={cn(SHARED_STYLES, VARIANT_STYLES[variant], className)}>{children}</div>

export const SearchBarDivider = (): JSX.Element => <div className="w-px bg-[var(--color-border-primary)] shrink-0" />
