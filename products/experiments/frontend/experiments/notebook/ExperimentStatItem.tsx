import { LemonSkeleton } from '@posthog/lemon-ui'

export interface ExperimentStatItemProps {
    label: string
    value: string | number
    loading?: boolean
    chart?: React.ReactNode
}

export function ExperimentStatItem({ label, value, loading, chart }: ExperimentStatItemProps): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted">{label}</span>
            <div className="flex items-center gap-1.5">
                {loading ? (
                    <LemonSkeleton className="w-12 h-4" />
                ) : (
                    <span className="font-semibold text-sm">{value}</span>
                )}
                {chart}
            </div>
        </div>
    )
}
