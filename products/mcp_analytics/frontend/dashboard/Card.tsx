import { cn } from '@posthog/quill-primitives'

export function Card({
    children,
    className,
    title,
}: {
    children: React.ReactNode
    className?: string
    title?: string
}): JSX.Element {
    return (
        <div className={cn('rounded-lg border border-primary bg-surface-primary px-3.5 py-3', className)}>
            {title ? <h3 className="mb-3 text-sm font-medium text-primary">{title}</h3> : null}
            {children}
        </div>
    )
}
