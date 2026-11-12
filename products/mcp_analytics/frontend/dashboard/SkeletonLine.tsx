import { cn, Skeleton } from '@posthog/quill-primitives'

// A placeholder in a text line box, so a placeholder table row is as tall as a row of text.
export function SkeletonLine({ className, style }: { className?: string; style?: React.CSSProperties }): JSX.Element {
    return (
        <div className="flex h-lh items-center">
            <Skeleton className={cn('h-3', className)} style={style} />
        </div>
    )
}
