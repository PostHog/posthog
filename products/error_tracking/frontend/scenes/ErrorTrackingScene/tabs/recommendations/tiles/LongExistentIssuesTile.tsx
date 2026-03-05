import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { recommendationsLogic } from '../recommendationsLogic'
import { RecommendationTile } from '../RecommendationTile'

export interface LongExistentIssue {
    id: string
    name: string
    occurrencesLast7Days: number
    firstSeenDaysAgo: number
}

function formatAge(days: number): string {
    if (days >= 365) {
        const years = Math.floor(days / 365)
        return `${years}y`
    }
    if (days >= 30) {
        const months = Math.floor(days / 30)
        return `${months}mo`
    }
    return `${days}d`
}

export function LongExistentIssuesTile({ issues }: { issues: LongExistentIssue[] }): JSX.Element {
    const { suppressedIssueIds } = useValues(recommendationsLogic)
    const { suppressIssue } = useActions(recommendationsLogic)

    const visibleIssues = issues.filter((i) => !suppressedIssueIds.includes(i.id))

    if (visibleIssues.length === 0) {
        return <></>
    }

    return (
        <RecommendationTile
            tileId="long-existent-issues"
            icon={<IconClock className="text-warning" />}
            title="Long-running active issues"
            category="Issues"
            priority="important"
        >
            <p className="text-xs text-secondary mb-2">
                These issues have been active for a long time and keep occurring. Consider suppressing or fixing them.
            </p>
            <div className="space-y-1">
                {visibleIssues.slice(0, 5).map((issue) => (
                    <div key={issue.id} className="flex items-center gap-2 bg-surface-alt rounded-lg px-3 py-2 group">
                        <div className="flex-1 min-w-0">
                            <p className="text-sm font-mono truncate mb-0">{issue.name}</p>
                            <div className="flex items-center gap-3 text-xs text-secondary">
                                <span>{issue.occurrencesLast7Days.toLocaleString()} occurrences / 7d</span>
                                <span className="text-border-bold">·</span>
                                <span>Active for {formatAge(issue.firstSeenDaysAgo)}</span>
                            </div>
                        </div>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            status="muted"
                            className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                            onClick={() => suppressIssue(issue.id)}
                        >
                            Suppress
                        </LemonButton>
                    </div>
                ))}
            </div>
            {visibleIssues.length > 5 ? (
                <p className="text-xs text-secondary mt-1">+ {visibleIssues.length - 5} more issues</p>
            ) : null}
        </RecommendationTile>
    )
}
