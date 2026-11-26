import { useActions, useValues } from 'kea'

import { LemonBanner, LemonModal, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { DigestRunApi } from '../../generated/api.schemas'
import { stamphogSceneLogic } from '../StamphogScene/stamphogSceneLogic'
import { digestDestinationLabel, digestRunHasDetails, digestStatusDisplay } from './digestDisplay'
import { DigestRunDetails } from './DigestRunDetails'
import { DIGESTS_PAGE_SIZE, stamphogDigestsSceneLogic } from './stamphogDigestsSceneLogic'

function DigestsTable(): JSX.Element {
    const { digestRuns, digestRunsCount, digestRunsResponseLoading, digestRunsFailed, page } =
        useValues(stamphogDigestsSceneLogic)
    const { setPage, loadDigestRuns, digestRunExpanded } = useActions(stamphogDigestsSceneLogic)

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
                rowExpandable: digestRunHasDetails,
                onRowExpand: digestRunExpanded,
            }}
            pagination={{
                controlled: true,
                pageSize: DIGESTS_PAGE_SIZE,
                currentPage: page,
                entryCount: digestRunsCount,
                onForward: () => setPage(page + 1),
                onBackward: () => setPage(page - 1),
            }}
            emptyState="No digests yet."
            data-attr="stamphog-digests-table"
        />
    )
}

export function DigestHistoryModal(): JSX.Element {
    const { repoConfigs, repoConfigsLoading, digestHistoryOpen } = useValues(stamphogSceneLogic)
    const { closeDigestHistory } = useActions(stamphogSceneLogic)
    // Nothing posts while no repository is in the digest, so the history says it is paused.
    const paused = !repoConfigsLoading && !repoConfigs.some((repo) => repo.digest_enabled)

    return (
        <LemonModal
            isOpen={digestHistoryOpen}
            onClose={closeDigestHistory}
            title={
                <span className="flex flex-wrap items-center gap-2">
                    Digest history
                    {paused && (
                        <LemonTag type="muted" size="small">
                            Paused
                        </LemonTag>
                    )}
                </span>
            }
            description={
                paused
                    ? 'Each Slack post of the merged pull requests that auto-approval approved. No repository is in the digest, so nothing is posted.'
                    : 'Each Slack post of the merged pull requests that auto-approval approved.'
            }
            width={960}
            data-attr="stamphog-digest-history-modal"
        >
            {/* Mounted only while open, so the digests load and the view event fires when someone looks. */}
            {digestHistoryOpen && <DigestsTable />}
        </LemonModal>
    )
}
