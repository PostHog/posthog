import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { AuthorFrictionTable } from '../components/AuthorFrictionTable'
import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { FrictionGroupLegend } from '../components/FrictionGroupLegend'
import { SourceScopeChip } from '../components/ScopeBar'
import { ScopePanel } from '../components/ScopePanel'
import { Section } from '../components/Section'
import { authorFrictionLogic } from './authorFrictionLogic'

export function EngineeringAnalyticsAuthors(): JSX.Element {
    const {
        friction,
        frictionLoading,
        frictionFailed,
        frictionNotConnected,
        authors,
        githubTeam,
        teamOptions,
        sourceId,
    } = useValues(authorFrictionLogic)
    const { loadFriction, setGithubTeam } = useActions(authorFrictionLogic)

    const maxScore = Math.max(0, ...(friction?.items ?? []).map((item) => item.score))

    if (frictionNotConnected) {
        return <ConnectGitHubSource />
    }

    const teamFilter = (
        <LemonSelect
            size="small"
            value={githubTeam}
            onChange={(value) => setGithubTeam(value)}
            options={[
                { value: null, label: 'All teams' },
                ...teamOptions.map((team) => ({ value: team, label: team })),
            ]}
            disabledReason={
                !friction
                    ? 'Teams load with the friction list.'
                    : !friction.has_membership_data
                      ? 'Team membership is not synced for this source.'
                      : teamOptions.length === 0
                        ? 'No team has a member with a friction score yet.'
                        : undefined
            }
            data-attr="engineering-analytics-friction-team-filter"
        />
    )

    return (
        <div className="flex flex-col gap-4">
            <ScopePanel busy={frictionLoading && !!friction} controls={<SourceScopeChip pickerOnly />}>
                <Section
                    id="author-friction"
                    title="Friction by author"
                    note={<FrictionGroupLegend />}
                    right={teamFilter}
                >
                    {frictionFailed ? (
                        <CIAnalyticsLoadError onRetry={loadFriction} loading={frictionLoading} />
                    ) : friction && !friction.available ? (
                        <div className="text-sm text-secondary" data-attr="engineering-analytics-friction-not-ready">
                            Friction is not ready for this project yet. It needs a GitHub source with workflow runs,
                            workflow jobs and pull requests synced, and it refreshes every 12 hours.
                        </div>
                    ) : (
                        <AuthorFrictionTable
                            authors={authors}
                            rankedAuthorCount={friction?.ranked_author_count ?? 0}
                            windowDays={friction?.window_days ?? 30}
                            maxScore={maxScore}
                            loading={frictionLoading}
                            sourceId={sourceId}
                            emptyState={
                                githubTeam
                                    ? 'No one on this team has 3 merged pull requests in the window yet.'
                                    : 'No author has 3 merged pull requests in the window yet.'
                            }
                            dataAttr="engineering-analytics-friction-table"
                        />
                    )}
                </Section>
            </ScopePanel>
        </div>
    )
}
