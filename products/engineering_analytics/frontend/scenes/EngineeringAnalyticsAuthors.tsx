import { useActions, useValues } from 'kea'

import { LemonSelect, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { urls } from 'scenes/urls'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { CountCell } from '../components/CountCell'
import { FrictionGroupBar } from '../components/FrictionGroupBar'
import { FrictionGroupLegend } from '../components/FrictionGroupLegend'
import { SourceScopeChip } from '../components/ScopeBar'
import { ScopePanel } from '../components/ScopePanel'
import { Section } from '../components/Section'
import type { AuthorFrictionApi } from '../generated/api.schemas'
import { timesTypical } from '../lib/format'
import { FRICTION_GROUP_DESCRIPTIONS, FRICTION_GROUP_LABELS, FRICTION_GROUP_ORDER } from '../lib/friction'
import { rowNavigationProps } from '../lib/rowNavigation'
import { withCurrentScope } from '../lib/scope'
import { authorFrictionLogic } from './authorFrictionLogic'

function authorUrl(handle: string, sourceId: string | null): string {
    return withCurrentScope(urls.engineeringAnalyticsAuthor(handle), sourceId)
}

const GROUPS_TOOLTIP = FRICTION_GROUP_ORDER.map(
    (group) => `${FRICTION_GROUP_LABELS[group]}: ${FRICTION_GROUP_DESCRIPTIONS[group]}.`
).join(' ')

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

    const windowLabel = `last ${friction?.window_days ?? 30} days`
    const maxScore = Math.max(0, ...(friction?.items ?? []).map((item) => item.score))

    const columns: LemonTableColumns<AuthorFrictionApi> = [
        {
            title: 'Rank',
            key: 'rank',
            width: 90,
            tooltip: `Position by friction among ${friction?.ranked_author_count ?? 0} authors. The range is where the author lands when their pull requests are resampled, so a wide range means the position is not settled.`,
            sorter: (a, b) => a.rank - b.rank,
            render: (_, row) => (
                <span className="tabular-nums">
                    {row.rank}
                    {row.rank_low !== row.rank_high && (
                        <span className="text-tertiary">
                            {' '}
                            ({row.rank_low}–{row.rank_high})
                        </span>
                    )}
                </span>
            ),
        },
        {
            title: 'Author',
            key: 'author',
            sorter: (a, b) => a.author.localeCompare(b.author),
            render: (_, row) => (
                <div className="flex items-center gap-2">
                    {row.avatar_url ? (
                        <img src={row.avatar_url} alt="" className="size-5 shrink-0 rounded-full" />
                    ) : (
                        <Lettermark name={row.author} size="small" />
                    )}
                    <Link
                        to={authorUrl(row.author, sourceId)}
                        className="text-xs font-medium"
                        data-attr="engineering-analytics-friction-author-link"
                    >
                        {row.author}
                    </Link>
                </div>
            ),
        },
        {
            title: 'Friction',
            key: 'score',
            width: 90,
            align: 'right',
            tooltip: `Friction over pull requests merged in the ${windowLabel}, as a multiple of the typical author: 1.0× is typical. It counts what happened to the author, never how much or how fast they ship.`,
            sorter: (a, b) => a.score - b.score,
            render: (_, row) => <span className="tabular-nums">{timesTypical(row.score)}</span>,
        },
        {
            title: 'Where it comes from',
            key: 'groups',
            width: '40%',
            tooltip: GROUPS_TOOLTIP,
            render: (_, row) => <FrictionGroupBar groups={row.groups} max={maxScore} />,
        },
        {
            title: 'Pull requests',
            key: 'pr_count',
            width: 110,
            align: 'right',
            tooltip: `Merged in the ${windowLabel}. An author needs 3 to get a score.`,
            render: (_, row) => <CountCell value={row.pr_count} />,
        },
    ]

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
                        <LemonTable
                            data-attr="engineering-analytics-friction-table"
                            size="small"
                            columns={columns}
                            dataSource={authors}
                            rowKey={(row) => row.author}
                            rowClassName="cursor-pointer"
                            onRow={(row) => rowNavigationProps(authorUrl(row.author, sourceId))}
                            loading={frictionLoading}
                            useURLForSorting={false}
                            emptyState={
                                githubTeam
                                    ? 'No one on this team has 3 merged pull requests in the window yet.'
                                    : 'No author has 3 merged pull requests in the window yet.'
                            }
                            nouns={['author', 'authors']}
                        />
                    )}
                </Section>
            </ScopePanel>
        </div>
    )
}
