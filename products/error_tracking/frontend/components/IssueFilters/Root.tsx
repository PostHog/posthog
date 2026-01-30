import React from 'react'

import { cn } from 'lib/utils/css-classes'

export const ErrorFiltersRoot = ({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element => {
    return <div className={cn('space-y-2', className)}>{children}</div>
}
