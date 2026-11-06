import type { ReactNode } from 'react'

export function GoalStat({ label, value }: { label: string; value?: ReactNode }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate text-xs text-tertiary">{label}</span>
            {value !== undefined && <span className="text-sm font-semibold tabular-nums">{value}</span>}
        </div>
    )
}
