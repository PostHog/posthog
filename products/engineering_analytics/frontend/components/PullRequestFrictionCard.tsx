import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import type { PullRequestFrictionDetailApi } from '../generated/api.schemas'
import { timesTypical } from '../lib/format'
import { FRICTION_GROUP_COLORS, pullRequestFrictionFacts } from '../lib/friction'
import { ComparisonBarRow } from './ComparisonBarRow'
import { FrictionGroupLegend } from './FrictionGroupLegend'
import { FrictionGroupSegments } from './FrictionGroupSegments'

/** One merged pull request's friction next to the typical pull request, and what added it. */
export function PullRequestFrictionCard({
    friction,
    loading,
}: {
    friction: PullRequestFrictionDetailApi | null
    loading: boolean
}): JSX.Element {
    if (loading && !friction) {
        return (
            <LemonCard hoverEffect={false} className="p-4">
                <LemonSkeleton className="h-16 w-full" />
            </LemonCard>
        )
    }
    if (!friction || !friction.available) {
        return (
            <LemonCard hoverEffect={false} className="p-4 text-sm text-secondary">
                Friction is not ready for this project yet. It needs a GitHub source with workflow runs, workflow jobs
                and pull requests synced, and it refreshes every 12 hours.
            </LemonCard>
        )
    }
    const pr = friction.pull_request
    if (!pr) {
        return (
            <LemonCard hoverEffect={false} className="p-4 text-sm text-secondary">
                Friction covers pull requests merged in the last {friction.window_days} days, not authored by a bot.
            </LemonCard>
        )
    }

    const facts = pullRequestFrictionFacts(pr)
    const max = Math.max(pr.score, 1)
    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col gap-4 p-4"
            data-attr="engineering-analytics-pull-request-friction"
        >
            <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-2xl font-semibold leading-none tabular-nums">{timesTypical(pr.score)}</span>
                <span className="text-xs text-tertiary">the typical pull request</span>
            </div>
            <div className="flex flex-col gap-1.5">
                <ComparisonBarRow label="This pull request" value={pr.score} max={max} formatValue={timesTypical}>
                    <FrictionGroupSegments groups={pr.groups} />
                </ComparisonBarRow>
                <ComparisonBarRow label="Typical" value={1} max={max} formatValue={timesTypical} muted />
            </div>
            <div className="text-xs text-tertiary">
                <FrictionGroupLegend />
            </div>
            {facts.length > 0 ? (
                <div className="grid max-w-xl grid-cols-[auto_1fr_auto] items-center gap-x-2 gap-y-1 text-xs">
                    {facts.map((fact) => (
                        <div key={fact.label} className="contents">
                            <span className={`size-2 rounded-sm ${FRICTION_GROUP_COLORS[fact.group]}`} />
                            <span className="text-secondary">{fact.label}</span>
                            <span className="text-right font-medium tabular-nums">{fact.value}</span>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="text-xs text-secondary">Nothing added friction to this pull request.</div>
            )}
        </LemonCard>
    )
}
