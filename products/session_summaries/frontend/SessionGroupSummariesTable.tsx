import { useActions, useValues } from 'kea'

import { IconEllipsis, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { sessionGroupSummariesTableLogic } from './sessionGroupSummariesTableLogic'
import { SessionGroupSummaryListItemType } from './types'

export const scene: SceneExport = {
    component: SessionGroupSummariesTable,
}

function titleColumn(): LemonTableColumn<SessionGroupSummaryListItemType, 'title'> {
    return {
        title: 'Title',
        dataIndex: 'title',
        width: '100%',
        render: function Render(title, { id }) {
            return (
                <Link data-attr="session-group-summary-title" to={urls.sessionSummary(id)} className="font-semibold">
                    {title || 'Untitled'}
                </Link>
            )
        },
        sorter: true,
    }
}

function sessionCountColumn(): LemonTableColumn<SessionGroupSummaryListItemType, 'session_count'> {
    return {
        title: 'Sessions',
        dataIndex: 'session_count',
        render: function Render(session_count) {
            return session_count
        },
        sorter: true,
    }
}

export function SessionGroupSummariesTable(): JSX.Element {
    const { filters, sessionGroupSummariesResponseLoading, tableSorting, pagination, sessionGroupSummaries } =
        useValues(sessionGroupSummariesTableLogic)
    const { loadSessionGroupSummaries, setFilters, tableSortingChanged, deleteSessionGroupSummary } = useActions(
        sessionGroupSummariesTableLogic
    )
    useOnMountEffect(loadSessionGroupSummaries)
    const columns: LemonTableColumns<SessionGroupSummaryListItemType> = [
        titleColumn() as LemonTableColumn<
            SessionGroupSummaryListItemType,
            keyof SessionGroupSummaryListItemType | undefined
        >,
        sessionCountColumn() as LemonTableColumn<
            SessionGroupSummaryListItemType,
            keyof SessionGroupSummaryListItemType | undefined
        >,
        createdByColumn<SessionGroupSummaryListItemType>() as LemonTableColumn<
            SessionGroupSummaryListItemType,
            keyof SessionGroupSummaryListItemType | undefined
        >,
        atColumn<SessionGroupSummaryListItemType>('created_at', 'Created') as LemonTableColumn<
            SessionGroupSummaryListItemType,
            keyof SessionGroupSummaryListItemType | undefined
        >,
        {
            render: function Render(_, summary) {
                return (
                    <LemonMenu
                        items={[
                            {
                                label: 'Delete',
                                icon: <IconTrash />,
                                status: 'danger',
                                onClick: () => {
                                    deleteSessionGroupSummary(summary.id)
                                },
                            },
                        ]}
                    >
                        <LemonButton aria-label="more" icon={<IconEllipsis />} size="small" />
                    </LemonMenu>
                )
            },
        },
    ]
    const config = sceneConfigurations[Scene.SessionGroupSummariesTable]
    return (
        <SceneContent>
            <SceneTitleSection
                name={config.name}
                description={config.description}
                resourceType={{
                    type: config.iconType || 'notebook',
                }}
                actions={<LemonTag type="warning">BETA</LemonTag>}
            />
            <div className="deprecated-space-y-4">
                <div className="flex justify-between gap-2 flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Search for summaries"
                        onChange={(s) => {
                            setFilters({ search: s })
                        }}
                        value={filters.search}
                        data-attr="session-group-summaries-search"
                    />
                    <div className="flex items-center gap-2 flex-wrap">
                        <div className="flex items-center gap-2">
                            <span>Created by:</span>
                            <MemberSelect
                                value={filters.createdBy}
                                onChange={(user) => setFilters({ createdBy: user?.uuid || null })}
                            />
                        </div>
                    </div>
                </div>
                <LemonTable
                    data-attr="session-group-summaries-table"
                    pagination={pagination}
                    dataSource={sessionGroupSummaries}
                    rowKey="id"
                    columns={columns}
                    loading={sessionGroupSummariesResponseLoading}
                    defaultSorting={tableSorting}
                    emptyState="No session group summaries matching your filters!"
                    nouns={['summary', 'summaries']}
                    onSort={tableSortingChanged}
                />
            </div>
        </SceneContent>
    )
}
