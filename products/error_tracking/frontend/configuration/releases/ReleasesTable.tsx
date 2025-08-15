import { IconTrash } from '@posthog/icons'
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
                    <p className="text-muted mt-2">
                        This will delete all sourcemaps associated with this release and cannot be undone.
                    </p>
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

    const columns: LemonTableColumns<ErrorTrackingRelease> = [
        {
            title: 'Project',
            dataIndex: 'project',
            key: 'project',
            render: (_, release) => <strong>{release.project}</strong>,
        },
        {
            title: 'Version',
            dataIndex: 'version',
            key: 'version',
            render: (_, release) => <div className="truncate w-[150px]">{release.version}</div>,
        },
        {
            title: 'Repository',
            key: 'repository',
            render: (_, release) => {
                if (release?.metadata?.git && release.metadata.git.repo_name) {
                    return <span className="text-muted-alt">{release.metadata.git.repo_name}</span>
                }
            },
        },
        {
            title: 'Branch',
            key: 'branch',
            render: (_, release) => {
                if (release?.metadata?.git && release.metadata.git.branch) {
                    return <span className="text-muted-alt">{release.metadata.git.branch}</span>
                }
            },
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
            width: 0,
            render: (_, release) => (
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    status="danger"
                    tooltip="Delete release"
                    icon={<IconTrash />}
                    onClick={() => confirmDeleteRelease(release)}
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
