import { LemonSkeleton } from '@posthog/lemon-ui'

export function StatCard({
    label,
    value,
    caption,
    loading,
}: {
    label: string
    value: string
    caption: string
    loading: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1 rounded-lg border bg-surface-primary p-4">
            <div className="text-xs text-secondary">{label}</div>
            {loading ? (
                <LemonSkeleton className="h-8 w-20" />
            ) : (
                <div className="text-2xl font-bold leading-tight">{value}</div>
            )}
            <div className="text-xs text-tertiary">{caption}</div>
        </div>
    )
}
