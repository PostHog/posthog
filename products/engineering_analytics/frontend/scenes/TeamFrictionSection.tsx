import { useActions, useValues } from 'kea'

import { AuthorFrictionTable } from '../components/AuthorFrictionTable'
import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { FrictionGroupLegend } from '../components/FrictionGroupLegend'
import { Section } from '../components/Section'
import { timesTypical } from '../lib/format'
import { authorFrictionLogic } from './authorFrictionLogic'

/** A team's median friction and its members by friction. Members keep their repository-wide ranks. */
export function TeamFrictionSection({ githubTeam }: { githubTeam: string }): JSX.Element {
    const { friction, frictionLoading, frictionFailed, frictionNotConnected, sourceId } = useValues(authorFrictionLogic)
    const { loadFriction } = useActions(authorFrictionLogic)

    const members = (friction?.items ?? []).filter((item) => (item.teams ?? []).includes(githubTeam))
    const team = (friction?.teams ?? []).find((entry) => entry.github_team === githubTeam)
    const maxScore = Math.max(0, ...(friction?.items ?? []).map((item) => item.score))

    return (
        <Section
            id="team-friction"
            title="Friction"
            note={
                <span className="flex flex-wrap items-center gap-2">
                    <span>Last {friction?.window_days ?? 30} days</span>
                    <FrictionGroupLegend />
                </span>
            }
            right={
                // During a reload the median still belongs to the previous scope, so it waits for the answer.
                team && !frictionLoading ? (
                    <span className="tabular-nums text-secondary">
                        {timesTypical(team.median_score)} median across {team.scored_author_count} members
                    </span>
                ) : undefined
            }
        >
            {frictionFailed ? (
                <CIAnalyticsLoadError onRetry={loadFriction} loading={frictionLoading} />
            ) : frictionNotConnected || (friction && !friction.available) ? (
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
                            : `No scored members found for this team in the last ${friction?.window_days ?? 30} days. A score needs 3 merged pull requests, and members come from the GitHub team with this name.`
                    }
                    dataAttr="engineering-analytics-team-friction-table"
                />
            )}
        </Section>
    )
}
