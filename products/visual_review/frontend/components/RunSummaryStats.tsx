import { IconX } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import type { RunSummaryApi } from '../generated/api.schemas'

interface RunSummaryStatsProps {
    summary: RunSummaryApi
    compact?: boolean
}

export function RunSummaryStats({ summary, compact }: RunSummaryStatsProps): JSX.Element {
    const hasChanges = summary.changed > 0 || summary.new > 0 || summary.removed > 0

    if (compact) {
        return (
            <div className="flex items-center gap-2 text-xs">
                {summary.changed > 0 && (
                    <span className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full shrink-0 bg-warning" />
                        <span className="text-warning-dark font-medium">{summary.changed}</span>
                    </span>
                )}
                {summary.new > 0 && (
                    <span className="flex items-center gap-1">
                        <span className="w-2 h-2 rounded-full shrink-0 bg-success" />
                        <span className="text-success font-medium">{summary.new}</span>
                    </span>
                )}
                {summary.removed > 0 && (
                    <span className="flex items-center gap-1">
                        <IconX className="w-3.5 h-3.5 shrink-0 text-danger" />
                        <span className="text-danger font-medium">{summary.removed}</span>
                    </span>
                )}
                {!hasChanges && <span className="text-muted">no changes</span>}
            </div>
        )
    }

    return (
        <div className="flex items-center gap-1.5">
            {summary.changed > 0 && <LemonTag type="warning">{summary.changed} changed</LemonTag>}
            {summary.new > 0 && <LemonTag type="success">{summary.new} new</LemonTag>}
            {summary.removed > 0 && <LemonTag type="danger">{summary.removed} removed</LemonTag>}
            <LemonTag type="muted">{summary.unchanged} unchanged</LemonTag>
        </div>
    )
}
