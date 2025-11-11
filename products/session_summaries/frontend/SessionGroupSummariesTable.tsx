import { useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { atColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { Link } from '~/lib/lemon-ui/Link'

import { SessionGroupSummaryListItem, sessionGroupSummariesTableLogic } from './sessionGroupSummariesTableLogic'

export const scene: SceneExport = {
    component: SessionGroupSummariesTable,
}

function nameColumn(): LemonTableColumn<SessionGroupSummaryListItem, 'name'> {
    return {
        title: 'Name',
        dataIndex: 'name',
        width: '100%',
        render: function Render(name, { session_group_id }) {
            return (
                <Link
                    data-attr="session-group-summary-name"
                    to={urls.sessionSummary(session_group_id)}
                    className="font-semibold"
                >
                    {name || 'Untitled'}
                </Link>
            )
        },
        sorter: (a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'),
    }
}

export function SessionGroupSummariesTable(): JSX.Element {
    const { sessionGroupSummaries } = useValues(sessionGroupSummariesTableLogic)

    const columns: LemonTableColumns<SessionGroupSummaryListItem> = [
        nameColumn() as LemonTableColumn<SessionGroupSummaryListItem, keyof SessionGroupSummaryListItem | undefined>,
        atColumn<SessionGroupSummaryListItem>('created_at', 'Created') as LemonTableColumn<
            SessionGroupSummaryListItem,
            keyof SessionGroupSummaryListItem | undefined
        >,
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Session summaries"
                resourceType={{
                    type: 'insight/hog',
                }}
            />
            <LemonTable
                data-attr="session-group-summaries-table"
                dataSource={sessionGroupSummaries}
                rowKey="session_group_id"
                columns={columns}
                loading={false}
                emptyState="No session group summaries available"
                nouns={['summary', 'summaries']}
            />
        </SceneContent>
    )
}
