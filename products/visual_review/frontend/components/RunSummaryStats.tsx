import type { RunSummaryApi } from '../generated/api.schemas'

interface RunSummaryStatsProps {
    summary: RunSummaryApi
}

export function RunSummaryStats({ summary }: RunSummaryStatsProps): JSX.Element {
    return (
        <div className="flex gap-4 text-sm">
            {summary.changed > 0 && <span className="text-warning-dark font-medium">{summary.changed} changed</span>}
            {summary.new > 0 && <span className="text-primary font-medium">{summary.new} new</span>}
            {summary.removed > 0 && <span className="text-danger font-medium">{summary.removed} removed</span>}
            <span className="text-muted">{summary.unchanged} unchanged</span>
        </div>
    )
}
