import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSwitch, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { ReviewRunApi, StamphogRepoConfigApi } from '../../generated/api.schemas'
import { stamphogSceneLogic } from './stamphogSceneLogic'

export const scene: SceneExport = {
    component: StamphogScene,
    logic: stamphogSceneLogic,
}

const VERDICT_TAG_TYPE: Record<string, 'success' | 'danger' | 'warning' | 'default'> = {
    approved: 'success',
    refused: 'danger',
    escalate: 'warning',
    wait: 'warning',
    error: 'danger',
    none: 'default',
}

function ConnectRepositoryButton(): JSX.Element {
    const { installUrl, installInfoLoading } = useValues(stamphogSceneLogic)
    return (
        <LemonButton
            type="primary"
            icon={<IconGithub />}
            to={installUrl || undefined}
            targetBlank
            disableClientSideRouting
            disabledReason={
                installInfoLoading
                    ? 'Loading install details'
                    : installUrl
                      ? undefined
                      : 'GitHub App not configured yet'
            }
        >
            Connect a repository
        </LemonButton>
    )
}

function SyncedBanner(): JSX.Element | null {
    const { syncedRepos, skippedRepos } = useValues(stamphogSceneLogic)

    if (syncedRepos.length === 0) {
        return null
    }

    return (
        <LemonBanner type="success">
            <p className="font-medium">Stamphog is now watching these repositories</p>
            <ul className="list-disc list-inside">
                {syncedRepos.map((repo) => (
                    <li key={repo.id}>{repo.repository}</li>
                ))}
            </ul>
            {skippedRepos.length > 0 && (
                <p className="text-warning mt-2">
                    Skipped {skippedRepos.join(', ')} because another team already owns them under this installation.
                </p>
            )}
        </LemonBanner>
    )
}

function RepoConfigsTable(): JSX.Element {
    const { repoConfigs, repoConfigsLoading, updatingRepoIds } = useValues(stamphogSceneLogic)
    const { setRepoEnabled, setDigestEnabled } = useActions(stamphogSceneLogic)

    const columns: LemonTableColumns<StamphogRepoConfigApi> = [
        {
            title: 'Repository',
            dataIndex: 'repository',
            render: (repository) => <span className="font-medium">{repository as string}</span>,
        },
        {
            title: 'Enabled',
            key: 'enabled',
            render: (_, repo) => (
                <LemonSwitch
                    checked={!!repo.enabled}
                    disabledReason={updatingRepoIds.includes(repo.id) ? 'Updating' : undefined}
                    onChange={(checked) => setRepoEnabled(repo.id, checked)}
                />
            ),
        },
        {
            title: 'Digest enabled',
            key: 'digest_enabled',
            render: (_, repo) => (
                <LemonSwitch
                    checked={!!repo.digest_enabled}
                    disabledReason={updatingRepoIds.includes(repo.id) ? 'Updating' : undefined}
                    onChange={(checked) => setDigestEnabled(repo.id, checked)}
                />
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (created_at) => <TZLabel time={created_at as string} />,
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={repoConfigs}
            loading={repoConfigsLoading}
            rowKey="id"
            emptyState="No repositories yet. Install the Stamphog GitHub App to get started."
        />
    )
}

function ReviewRunsTable(): JSX.Element {
    const { reviewRuns, reviewRunsLoading } = useValues(stamphogSceneLogic)

    const columns: LemonTableColumns<ReviewRunApi> = [
        {
            title: 'PR',
            key: 'pr_number',
            render: (_, run) => (
                <Link to={run.pr_url} target="_blank">
                    #{run.pr_number}
                </Link>
            ),
        },
        {
            title: 'Repository',
            dataIndex: 'repository',
        },
        {
            title: 'Status',
            dataIndex: 'status',
            render: (status) => <LemonTag>{status as string}</LemonTag>,
        },
        {
            title: 'Verdict',
            dataIndex: 'verdict',
            render: (verdict) => (
                <LemonTag type={VERDICT_TAG_TYPE[verdict as string] ?? 'default'}>{verdict as string}</LemonTag>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (created_at) => <TZLabel time={created_at as string} />,
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={reviewRuns}
            loading={reviewRunsLoading}
            rowKey="id"
            emptyState="No review runs yet."
        />
    )
}

export function StamphogScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Stamphog"
                description="Automated pull request reviews and merged-PR digests, per repository."
                resourceType={{ type: 'task' }}
                actions={<ConnectRepositoryButton />}
            />
            <SyncedBanner />
            <div>
                <h3>Repositories</h3>
                <RepoConfigsTable />
            </div>
            <div>
                <h3>Recent review runs</h3>
                <ReviewRunsTable />
            </div>
        </SceneContent>
    )
}

export default StamphogScene
