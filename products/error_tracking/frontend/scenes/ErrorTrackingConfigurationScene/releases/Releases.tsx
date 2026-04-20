import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { ErrorTrackingRelease } from 'lib/components/Errors/types'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { GitMetadataParser } from 'products/error_tracking/frontend/components/ReleasesPreview/gitMetadataParser'

import { releasesLogic } from './releasesLogic'

export function Releases(): JSX.Element {
    const { loadReleases } = useActions(releasesLogic)

    useEffect(() => {
        loadReleases()
    }, [loadReleases])

    return (
        <div className="deprecated-space-y-4">
            <p>
                Releases are versions of your application that have been deployed. They are automatically created when
                you upload sourcemaps to PostHog.
            </p>
            <p>
                Each release can include git metadata such as the commit SHA, branch, and repository URL, which helps
                you track down the source of errors.
            </p>
            <div className="space-y-2">
                <ReleasesTable />
            </div>
        </div>
    )
}

const ReleasesTable = (): JSX.Element => {
    // @ts-expect-error: typegen typing issue
    const { pagination, releases, releaseResponseLoading } = useValues(releasesLogic)

    const columns: LemonTableColumns<ErrorTrackingRelease> = [
        {
            title: 'Version',
            width: 200,
            render: (_, { version }) => {
                return (
                    <div className="truncate w-100 overflow-hidden py-0.5" title={version}>
                        {version}
                    </div>
                )
            },
        },
        {
            title: 'Project',
            render: (_, { project }) => {
                return project ? (
                    <div className="truncate" title={project}>
                        {project}
                    </div>
                ) : (
                    <span className="text-muted">-</span>
                )
            },
        },
        {
            title: 'Commit',
            render: (_, { metadata }) => {
                const commitId = metadata?.git?.commit_id
                const commitLink = GitMetadataParser.getCommitLink(metadata?.git?.remote_url, commitId)
                return (
                    <Link to={commitLink} target="_blank" className="flex items-center gap-1" tooltip="Open commit">
                        {commitId ? commitId.substring(0, 7) : '-'}
                        {commitLink && <IconExternal className="text-xs" />}
                    </Link>
                )
            },
        },
        {
            title: 'Branch',
            render: (_, { metadata }) => {
                const branch = metadata?.git?.branch
                const branchLink = GitMetadataParser.getBranchLink(metadata?.git?.remote_url, metadata?.git?.branch)
                return (
                    <Link to={branchLink} target="_blank" className="flex items-center gap-1" tooltip="Open branch">
                        {branch ?? '-'}
                        {branchLink && <IconExternal className="text-xs" />}
                    </Link>
                )
            },
        },
        {
            title: 'Repository',
            render: (_, { metadata }) => {
                const remoteUrl = metadata?.git?.remote_url
                const repoName = metadata?.git?.repo_name
                let repoLink = GitMetadataParser.getRepoLink(remoteUrl)
                return (
                    <Link to={repoLink} target="_blank" className="flex items-center gap-1" tooltip="Open repository">
                        {repoName ?? '-'}
                        {repoLink && <IconExternal className="text-xs" />}
                    </Link>
                )
            },
        },
        {
            title: 'Created at',
            dataIndex: 'created_at',
            render: (data) => humanFriendlyDetailedTime(data as string),
        },
    ]

    const emptyState = (
        <div className="flex flex-col justify-center items-center gap-2 p-4 text-center">
            <div className="font-semibold">No releases found</div>
            <div className="text-secondary">
                Releases are automatically created when PostHog detects version information in your error tracking data.
                Learn more in the{' '}
                <Link to="https://posthog.com/docs/error-tracking" target="_blank">
                    docs
                </Link>
                .
            </div>
        </div>
    )

    return (
        <LemonTable<ErrorTrackingRelease>
            id="releases"
            pagination={pagination}
            columns={columns}
            loading={releaseResponseLoading}
            dataSource={releases}
            emptyState={!releaseResponseLoading ? emptyState : undefined}
        />
    )
}
