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
            <div className="flex items-center gap-1">
                {summary.changed > 0 && (
                    <LemonTag type="warning" size="small">
                        {summary.changed} changed
                    </LemonTag>
                )}
                {summary.new > 0 && (
                    <LemonTag type="highlight" size="small">
                        {summary.new} new
                    </LemonTag>
                )}
                {summary.removed > 0 && (
                    <LemonTag type="danger" size="small">
                        {summary.removed} removed
                    </LemonTag>
                )}
                {!hasChanges && (
                    <LemonTag type="muted" size="small">
                        no changes
                    </LemonTag>
                )}
            </div>
        )
    }

    return (
        <div className="flex items-center gap-1.5">
            {summary.changed > 0 && <LemonTag type="warning">{summary.changed} changed</LemonTag>}
            {summary.new > 0 && <LemonTag type="highlight">{summary.new} new</LemonTag>}
            {summary.removed > 0 && <LemonTag type="danger">{summary.removed} removed</LemonTag>}
            <LemonTag type="muted">{summary.unchanged} unchanged</LemonTag>
        </div>
    )
}
