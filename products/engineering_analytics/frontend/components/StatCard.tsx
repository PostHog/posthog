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
        <div className="flex flex-col gap-1 rounded-md bg-surface-secondary px-3.5 py-3">
            <div className="text-[11px] uppercase tracking-wide text-secondary">{label}</div>
            {loading ? (
                <LemonSkeleton className="h-7 w-12" />
            ) : (
                <div className="text-2xl font-semibold leading-tight">{value}</div>
            )}
            <div className="text-[11px] text-tertiary">{caption}</div>
        </div>
    )
}
