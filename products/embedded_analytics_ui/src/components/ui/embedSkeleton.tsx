import { cn } from '../../utils'
import { ReactNode } from 'react'

function EmbedSkeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>): ReactNode {
    return <div className={cn('analytics-skeleton', className)} {...props} />
}

export { EmbedSkeleton }
