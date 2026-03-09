import type { RunSummaryApi } from '../generated/api.schemas'

interface RunSummaryStatsProps {
    summary: RunSummaryApi
    compact?: boolean
}

export function RunSummaryStats({ summary, compact }: RunSummaryStatsProps): JSX.Element {
    const hasChanges = summary.changed > 0 || summary.new > 0 || summary.removed > 0

    if (compact) {
        // Build secondary breakdown (new/removed only)
        const secondaryParts: string[] = []
        if (summary.new > 0) {
            secondaryParts.push(`${summary.new} new`)
        }
        if (summary.removed > 0) {
            secondaryParts.push(`${summary.removed} removed`)
        }

        const hasChanged = summary.changed > 0

        return (
            <div className="flex flex-col gap-0.5 min-w-[100px]">
                {/* Primary: changed count (dominant) */}
                <div className={hasChanged ? 'text-warning-dark' : 'text-muted'}>
                    <span className="text-base font-semibold">{summary.changed}</span>
                    <span className="text-xs ml-1">changed</span>
                </div>

                {/* Secondary: new/removed breakdown (subordinate) */}
                {secondaryParts.length > 0 ? (
                    <div className="text-xs text-muted">{secondaryParts.join(' · ')}</div>
                ) : !hasChanges ? (
                    <div className="text-xs text-muted">no diffs</div>
                ) : null}
            </div>
        )
    }

    return (
        <div className="flex gap-3 text-sm">
            {summary.changed > 0 && <span className="text-warning-dark font-medium">{summary.changed} changed</span>}
            {summary.new > 0 && <span className="text-success font-medium">{summary.new} new</span>}
            {summary.removed > 0 && <span className="text-danger font-medium">{summary.removed} removed</span>}
            <span className="text-muted">{summary.unchanged} unchanged</span>
        </div>
    )
}
