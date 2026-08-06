import { HTMLProps } from 'react'

import { cn } from 'lib/utils/css-classes'

export function SubHeader({ className, ...props }: HTMLProps<HTMLDivElement>): JSX.Element {
    return (
        <div className={cn('flex gap-1 items-center border-b-1 bg-[var(--gray-1)] px-2 h-9', className)} {...props} />
    )
}
