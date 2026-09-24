import { useActions, useValues } from 'kea'

import { AuthorFrictionTable } from '../components/AuthorFrictionTable'
import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { FrictionGroupLegend } from '../components/FrictionGroupLegend'
import { Section } from '../components/Section'
import { timesTypical } from '../lib/format'
import { authorFrictionLogic } from './authorFrictionLogic'

/** A team's median friction and its members by friction. Members keep their repository-wide ranks. */
export function TeamFrictionSection({ githubTeam }: { githubTeam: string }): JSX.Element {
    const { friction, frictionLoading, frictionFailed, sourceId } = useValues(authorFrictionLogic)
    const { loadFriction } = useActions(authorFrictionLogic)

    const members = (friction?.items ?? []).filter((item) => (item.teams ?? []).includes(githubTeam))
    const team = (friction?.teams ?? []).find((entry) => entry.github_team === githubTeam)
    const maxScore = Math.max(0, ...(friction?.items ?? []).map((item) => item.score))

    return (
        <Section
            id="team-friction"
            title="Friction"
            note={<FrictionGroupLegend />}
            right={
                team ? (
                    <span className="tabular-nums text-secondary">
                        {timesTypical(team.median_score)} median across {team.scored_author_count} members
                    </span>
                ) : undefined
            }
        >
            {frictionFailed ? (
                <CIAnalyticsLoadError onRetry={loadFriction} loading={frictionLoading} />
            ) : friction && !friction.available ? (
                <div className="text-sm text-secondary">
                    Friction is not ready for this project yet. It needs a GitHub source with workflow runs, workflow
                    jobs and pull requests synced, and it refreshes every 12 hours.
                </div>
            ) : (
                <AuthorFrictionTable
                    authors={members}
                    rankedAuthorCount={friction?.ranked_author_count ?? 0}
                    windowDays={friction?.window_days ?? 30}
                    maxScore={maxScore}
                    loading={frictionLoading}
                    sourceId={sourceId}
                    emptyState={
                        friction?.has_membership_data === false
                            ? 'Team membership is not synced for this source, so the team has no members to show.'
                            : 'No member of this team has 3 merged pull requests in the last 30 days yet.'
                    }
                    dataAttr="engineering-analytics-team-friction-table"
                />
            )}
        </Section>
    )
}
