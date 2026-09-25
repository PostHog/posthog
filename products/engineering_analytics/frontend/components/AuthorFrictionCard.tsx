import { LemonCard, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { AuthorFrictionDetailApi } from '../generated/api.schemas'
import { timesTypical } from '../lib/format'
import { withCurrentScope } from '../lib/scope'
import { ComparisonBarRow } from './ComparisonBarRow'
import { FrictionGroupBar } from './FrictionGroupBar'
import { FrictionGroupLegend } from './FrictionGroupLegend'
import { FrictionGroupSegments } from './FrictionGroupSegments'

/** One author's friction next to their teams and the typical author, and the pull requests behind it. */
export function AuthorFrictionCard({
    detail,
    loading,
    sourceId,
}: {
    detail: AuthorFrictionDetailApi | null
    loading: boolean
    sourceId: string | null
}): JSX.Element {
    if (loading && !detail) {
        return (
            <LemonCard hoverEffect={false} className="p-4">
                <LemonSkeleton className="h-24 w-full" />
            </LemonCard>
        )
    }
    if (!detail || !detail.available) {
        return (
            <LemonCard hoverEffect={false} className="p-4 text-sm text-secondary">
                Friction is not ready for this project yet. It needs a GitHub source with workflow runs, workflow jobs
                and pull requests synced, and it refreshes every 12 hours.
            </LemonCard>
        )
    }

    const author = detail.author
    const rows = [
        ...(author ? [{ label: 'This author', value: author.score, groups: author.groups, muted: false }] : []),
        ...detail.teams.map((team) => ({
            label: team.github_team,
            value: team.median_score,
            groups: null,
            muted: true,
            tooltip: `Median of ${team.scored_author_count} other scored members of ${team.github_team}.`,
        })),
        { label: 'Typical author', value: 1, groups: null, muted: true },
    ]
    const max = Math.max(...rows.map((row) => row.value))
    const topScore = Math.max(0, ...detail.pull_requests.map((pr) => pr.score))

    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col gap-4 p-4"
            data-attr="engineering-analytics-author-friction"
        >
            {author ? (
                <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-2xl font-semibold leading-none tabular-nums">
                        {timesTypical(author.score)}
                    </span>
                    <Tooltip title="Where the author lands among everyone scored, with the range from resampling their pull requests.">
                        <span className="cursor-default text-xs tabular-nums text-tertiary">
                            rank {author.rank} of {detail.ranked_author_count}
                            {author.rank_low !== author.rank_high && ` (${author.rank_low}–${author.rank_high})`}
                        </span>
                    </Tooltip>
                </div>
            ) : (
                <div className="text-sm text-secondary">
                    A score needs 3 merged pull requests in the last {detail.window_days} days. This author has{' '}
                    {detail.pr_count}.
                </div>
            )}
            <div className="flex flex-col gap-1.5">
                {rows.map((row, index) => (
                    <ComparisonBarRow
                        // A handle can equal a team slug, so the label alone is no unique key.
                        key={`${index}:${row.label}`}
                        label={row.label}
                        labelTooltip={'tooltip' in row ? row.tooltip : undefined}
                        value={row.value}
                        max={max}
                        formatValue={timesTypical}
                        muted={row.muted}
                    >
                        {row.groups ? <FrictionGroupSegments groups={row.groups} /> : undefined}
                    </ComparisonBarRow>
                ))}
            </div>
            <div className="text-xs text-tertiary">
                <FrictionGroupLegend />
            </div>
            {detail.pull_requests.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    <h3 className="m-0 text-xs font-semibold text-secondary">Pull requests with the most friction</h3>
                    {detail.pull_requests.map((pr) => (
                        <div key={`${pr.repo_owner}/${pr.repo_name}#${pr.number}`} className="flex items-center gap-3">
                            <Link
                                to={withCurrentScope(
                                    urls.engineeringAnalyticsPullRequest(pr.repo_owner, pr.repo_name, pr.number),
                                    sourceId
                                )}
                                className="min-w-0 flex-1 truncate text-xs"
                                data-attr="engineering-analytics-author-friction-pr-link"
                            >
                                <span className="tabular-nums text-tertiary">#{pr.number}</span> {pr.title}
                            </Link>
                            <div className="w-32 shrink-0">
                                <FrictionGroupBar groups={pr.groups} max={topScore} />
                            </div>
                            <Tooltip title="This pull request's friction as a multiple of the typical pull request.">
                                <span className="w-12 shrink-0 text-right text-xs font-medium tabular-nums">
                                    {timesTypical(pr.score)}
                                </span>
                            </Tooltip>
                        </div>
                    ))}
                </div>
            )}
        </LemonCard>
    )
}
