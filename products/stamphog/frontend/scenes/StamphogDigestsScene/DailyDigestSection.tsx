import { useActions, useValues } from 'kea'
import { Fragment, useEffect, useRef } from 'react'

import { LemonBanner, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { toAccessControlLevel } from 'lib/utils/accessControlUtils'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { PANE_LEFT, PANE_ROW } from 'products/review_hog/frontend/repositories/paneClasses'
import { RepositoryColumnHeaders } from 'products/review_hog/frontend/repositories/RepositoryColumnHeaders'

import { type CodeReviewApprovalRepositoryApi, DigestRunApi } from '../../generated/api.schemas'
import { editorDisabledReason } from '../StamphogScene/repoAccess'
import { stamphogSceneLogic } from '../StamphogScene/stamphogSceneLogic'
import { digestDestinationLabel, digestRunHasDetails, digestStatusDisplay } from './digestDisplay'
import { DigestRunDetails } from './DigestRunDetails'
import { DIGESTS_PAGE_SIZE, stamphogDigestsSceneLogic } from './stamphogDigestsSceneLogic'

// pinned: the /stamphog/digests redirect in the stamphog manifest links to this id.
const DAILY_DIGEST_ID = 'daily-digest'

function DigestSwitch({ repo }: { repo: CodeReviewApprovalRepositoryApi }): JSX.Element {
    const { updatingRepoIds } = useValues(stamphogSceneLogic)
    const { updateRepoConfig } = useActions(stamphogSceneLogic)

    return (
        <LemonSwitch
            aria-label={`Include ${repo.repository} in the digest`}
            checked={!!repo.digest_enabled}
            // The API refuses a digest without reviews, because the digest lists only approved merges.
            disabledReason={
                editorDisabledReason(toAccessControlLevel(repo.user_access_level)) ??
                (!repo.enabled
                    ? 'Pick an Approve option other than Paused first'
                    : updatingRepoIds.includes(repo.id)
                      ? 'Saving…'
                      : undefined)
            }
            onChange={(checked) => updateRepoConfig(repo.id, { digest_enabled: checked })}
            data-attr="stamphog-repo-digest-toggle"
        />
    )
}

function DigestRepositories(): JSX.Element | null {
    const { repoConfigs } = useValues(stamphogSceneLogic)
    if (repoConfigs.length === 0) {
        return null
    }

    return (
        <div className="@container">
            <div className="grid grid-cols-[minmax(0,1fr)_auto] overflow-hidden rounded border border-primary [&>*:nth-child(-n+2)]:border-t-0">
                <RepositoryColumnHeaders
                    columns={[
                        { label: 'Repository', pane: 'left' },
                        { label: 'In the digest', pane: 'left' },
                    ]}
                />
                {repoConfigs.map((repo) => (
                    <Fragment key={repo.id}>
                        <span
                            className={`min-w-0 truncate px-4 py-2 font-mono text-sm font-semibold ${PANE_LEFT} ${PANE_ROW}`}
                            title={repo.repository}
                        >
                            {repo.repository}
                        </span>
                        <span className={`flex items-center px-4 py-2 ${PANE_LEFT} ${PANE_ROW}`}>
                            <DigestSwitch repo={repo} />
                        </span>
                    </Fragment>
                ))}
            </div>
        </div>
    )
}

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

export function DailyDigestSection(): JSX.Element {
    const { repoConfigs, repoConfigsLoading } = useValues(stamphogSceneLogic)
    const sectionRef = useRef<HTMLDivElement>(null)
    // Nothing posts while no repository is in the digest, so the section says it is paused.
    const paused = !repoConfigsLoading && !repoConfigs.some((repo) => repo.digest_enabled)

    useEffect(() => {
        if (window.location.hash === `#${DAILY_DIGEST_ID}`) {
            sectionRef.current?.scrollIntoView()
        }
    }, [])

    return (
        <div id={DAILY_DIGEST_ID} ref={sectionRef}>
            <SceneSection
                title={
                    <span className="flex flex-wrap items-center gap-2">
                        Daily digest
                        {paused && (
                            <LemonTag type="muted" size="small">
                                Paused
                            </LemonTag>
                        )}
                    </span>
                }
                description={
                    paused
                        ? 'Posts the merged pull requests that auto-approval approved to Slack once a day. No repository is in the digest, so nothing is posted.'
                        : 'Posts the merged pull requests that auto-approval approved to Slack once a day.'
                }
            >
                <DigestRepositories />
                <h3 className="m-0 mt-2 text-sm font-semibold">Recent digests</h3>
                <DigestsTable />
            </SceneSection>
        </div>
    )
}
