import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { urls } from 'scenes/urls'

import type { AuthorFrictionApi } from '../generated/api.schemas'
import { timesTypical } from '../lib/format'
import { FRICTION_GROUP_DESCRIPTIONS, FRICTION_GROUP_LABELS, FRICTION_GROUP_ORDER } from '../lib/friction'
import { rowNavigationProps } from '../lib/rowNavigation'
import { withCurrentScope } from '../lib/scope'
import { CountCell } from './CountCell'
import { FrictionGroupBar } from './FrictionGroupBar'

function authorUrl(handle: string, sourceId: string | null): string {
    return withCurrentScope(urls.engineeringAnalyticsAuthor(handle), sourceId)
}

const GROUPS_TOOLTIP = FRICTION_GROUP_ORDER.map(
    (group) => `${FRICTION_GROUP_LABELS[group]}: ${FRICTION_GROUP_DESCRIPTIONS[group]}.`
).join(' ')

/** Authors by friction with their repository-wide ranks, whether the list shows everyone or one team. */
export function AuthorFrictionTable({
    authors,
    rankedAuthorCount,
    windowDays,
    maxScore,
    loading,
    sourceId,
    emptyState,
    dataAttr,
}: {
    authors: AuthorFrictionApi[]
    rankedAuthorCount: number
    windowDays: number
    /** The highest score in the repository, so bar lengths read the same on every page. */
    maxScore: number
    loading: boolean
    sourceId: string | null
    emptyState: string
    dataAttr: string
}): JSX.Element {
    const windowLabel = `last ${windowDays} days`
    const columns: LemonTableColumns<AuthorFrictionApi> = [
        {
            title: 'Rank',
            key: 'rank',
            width: 90,
            tooltip: `Position by friction among ${rankedAuthorCount} authors. The range is where the author lands when their pull requests are resampled, so a wide range means the position is not settled.`,
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
                        className="whitespace-nowrap text-xs font-medium"
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
    return (
        <LemonTable
            data-attr={dataAttr}
            size="small"
            columns={columns}
            dataSource={authors}
            rowKey={(row) => row.author}
            rowClassName="cursor-pointer"
            onRow={(row) => rowNavigationProps(authorUrl(row.author, sourceId))}
            loading={loading}
            useURLForSorting={false}
            emptyState={emptyState}
            nouns={['author', 'authors']}
        />
    )
}
