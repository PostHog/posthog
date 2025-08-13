import { IconExternal, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ErrorTrackingRelease } from 'lib/components/Errors/types'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { errorTrackingReleasesLogic } from './errorTrackingReleasesLogic'

export function ReleasesTable(): JSX.Element {
    const { releases, releaseResponseLoading, pagination } = useValues(errorTrackingReleasesLogic)
    const { deleteRelease } = useActions(errorTrackingReleasesLogic)

    const confirmDeleteRelease = (release: ErrorTrackingRelease): void => {
        LemonDialog.open({
            title: 'Delete release',
            description: (
                <div>
                    <p>
                        Are you sure you want to delete release <strong>{release.version}</strong> for project{' '}
                        <strong>{release.project}</strong>?
                    </p>
                    <p className="text-muted mt-2">This action cannot be undone.</p>
                </div>
            ),
            primaryButton: {
                children: 'Delete',
                type: 'primary',
                status: 'danger',
                onClick: () => deleteRelease(release.id),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }
    console.log(releases)

    const columns: LemonTableColumns<ErrorTrackingRelease> = [
        {
            title: 'Version',
            dataIndex: 'version',
            key: 'version',
            render: (_, release) => <strong>{release.version}</strong>,
        },
        {
            title: 'Project',
            dataIndex: 'project',
            key: 'project',
        },
        {
            title: 'Hash ID',
            dataIndex: 'hash_id',
            key: 'hash_id',
            render: (_, release) => (
                <span title={release.hash_id} className="font-mono text-xs">
                    {release.hash_id.substring(0, 12)}...
                </span>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            key: 'created_at',
            render: (_, release) => (
                <Tooltip title={humanFriendlyDetailedTime(release.created_at)}>
                    <TZLabel time={release.created_at} />
                </Tooltip>
            ),
        },
        {
            title: 'Metadata',
            dataIndex: 'metadata',
            key: 'metadata',
            render: (_, release) =>
                release.metadata && Object.keys(release.metadata).length > 0 ? (
                    <span className="text-muted-alt">
                        {Object.keys(release.metadata).length} field
                        {Object.keys(release.metadata).length !== 1 ? 's' : ''}
                    </span>
                ) : (
                    <span className="text-muted">None</span>
                ),
        },
        {
            title: 'GitHub',
            key: 'github_commit',
            width: 0,
            render: (_, release) => {
                const repoUrl = release.metadata?.repository_url || release.metadata?.github_url
                if (repoUrl && release.hash_id) {
                    const commitUrl = `${repoUrl}/commit/${release.hash_id}`
                    return (
                        <LemonButton
                            icon={<IconExternal />}
                            tooltip="View commit on GitHub"
                            onClick={() => window.open(commitUrl, '_blank')}
                            size="small"
                            type="secondary"
                        />
                    )
                }
                return null
            },
        },
        {
            width: 0,
            render: (_, release) => (
                <LemonButton
                    icon={<IconTrash />}
                    tooltip="Delete release"
                    onClick={() => confirmDeleteRelease(release)}
                    size="small"
                    status="danger"
                />
            ),
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={releases}
            loading={releaseResponseLoading}
            pagination={pagination}
            emptyState="No releases found. Releases are created when you upload source maps or configure error tracking in your application."
        />
    )
}
