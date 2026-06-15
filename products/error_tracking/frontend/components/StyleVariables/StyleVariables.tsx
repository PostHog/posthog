import './StyleVariables.scss'

import { cn } from 'lib/utils/css-classes'

export function StyleVariables({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element {
    return <div className={cn('ErrorTrackingVariables', className)}>{children}</div>
}
