import { HTMLProps } from 'react'

import { cn } from 'lib/utils/css-classes'

export function SubHeader({ className, ...props }: HTMLProps<HTMLDivElement>): JSX.Element {
    return (
        <div
            className={cn('flex h-9 items-center gap-1 border-b-1 border-border bg-[var(--muted)] px-2', className)}
            {...props}
        />
    )
}
