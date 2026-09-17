import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { StamphogTabs } from '../../components/StamphogTabs'
import { DigestRunApi } from '../../generated/api.schemas'
import { digestDestinationLabel, digestStatusDisplay } from './digestDisplay'
import { DIGESTS_PAGE_SIZE, stamphogDigestsSceneLogic } from './stamphogDigestsSceneLogic'

export const scene: SceneExport = {
    component: StamphogDigestsScene,
    logic: stamphogDigestsSceneLogic,
}

function DigestsTable(): JSX.Element {
    const { digestRuns, digestRunsCount, digestRunsResponseLoading, digestRunsFailed, page } =
        useValues(stamphogDigestsSceneLogic)
    const { setPage, loadDigestRuns } = useActions(stamphogDigestsSceneLogic)

    const columns: LemonTableColumns<DigestRunApi> = [
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (created_at) => <TZLabel time={created_at as string} />,
        },
        {
            title: 'Channel',
            key: 'slack_channel_id',
            render: (_, run) => <span className="font-mono text-xs">{digestDestinationLabel(run)}</span>,
        },
        {
            title: 'Audience',
            dataIndex: 'audience_key',
            render: (audience_key) => <span className="font-mono text-xs">{audience_key as string}</span>,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, run) => {
                const { type, label } = digestStatusDisplay(run)
                return <LemonTag type={type}>{label}</LemonTag>
            },
        },
        {
            title: 'PRs',
            dataIndex: 'pr_count',
            render: (pr_count) => <span className="font-mono text-xs">{pr_count as number}</span>,
        },
        {
            title: 'Posted',
            key: 'posted_at',
            render: (_, run) => (run.posted_at ? <TZLabel time={run.posted_at} /> : null),
        },
    ]

    if (digestRunsFailed) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadDigestRuns() }}
                data-attr="stamphog-digests-error"
            >
                Could not load digests. This is usually temporary.
            </LemonBanner>
        )
    }

    return (
        <LemonTable
            columns={columns}
            dataSource={digestRuns}
            loading={digestRunsResponseLoading}
            rowKey="id"
            expandable={{
                expandedRowRender: (run) => <DigestRunDetails run={run} />,
                rowExpandable: (run) => !!run.error || !!run.slack_message_ts,
            }}
            pagination={{
                controlled: true,
                pageSize: DIGESTS_PAGE_SIZE,
                currentPage: page,
                entryCount: digestRunsCount,
                onForward: () => setPage(page + 1),
                onBackward: () => setPage(page - 1),
            }}
            emptyState="No digests yet. Stamphog posts one per audience on its digest schedule."
            data-attr="stamphog-digests-table"
        />
    )
}

function DigestRunDetails({ run }: { run: DigestRunApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 pl-2 pr-4 py-4 text-xs">
            {run.error && <span className="font-mono text-danger break-all">{run.error}</span>}
            {run.slack_message_ts && (
                <span className="font-mono text-muted break-all">Slack message timestamp: {run.slack_message_ts}</span>
            )}
        </div>
    )
}

export function StamphogDigestsScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Digests"
                description="Every digest Stamphog posted, and where it went."
                resourceType={{ type: 'stamphog' }}
            />
            <StamphogTabs activeKey="digests" />
            <DigestsTable />
        </SceneContent>
    )
}

export default StamphogDigestsScene
