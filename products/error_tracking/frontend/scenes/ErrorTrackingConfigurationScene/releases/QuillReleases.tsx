import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import {
    Button,
    DataTable,
    DataTableProps,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Text,
    cn,
} from '@posthog/quill'

import { ErrorTrackingRelease } from 'lib/components/Errors/types'
import { GitMetadataParser } from 'lib/components/Git/gitMetadataParser'
import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { releasesLogic } from './releasesLogic'

function ExternalCellLink({
    to,
    tooltip,
    label,
}: {
    to: string | undefined
    tooltip: string
    label: string
}): JSX.Element {
    if (!to) {
        return <span translate="no">{label}</span>
    }

    return (
        <Button
            variant="link-foreground"
            size="sm"
            nativeButton={false}
            tooltip={tooltip}
            render={<LinkPrimitive to={to} target="_blank" />}
        >
            <span translate="no">{label}</span>
            <IconExternal />
        </Button>
    )
}

const COLUMNS: DataTableProps<ErrorTrackingRelease, unknown>['columns'] = [
    {
        id: 'version',
        header: 'Version',
        cell: ({ row }) => (
            <div className="max-w-50 truncate" title={row.original.version} translate="no">
                {row.original.version}
            </div>
        ),
    },
    {
        id: 'project',
        header: 'Project',
        cell: ({ row }) =>
            row.original.project ? (
                <div className="truncate" title={row.original.project} translate="no">
                    {row.original.project}
                </div>
            ) : (
                <span className="text-muted-foreground">-</span>
            ),
    },
    {
        id: 'commit',
        header: 'Commit',
        cell: ({ row }) => {
            const commitId = row.original.metadata?.git?.commit_id
            const commitLink = GitMetadataParser.getCommitLink(row.original.metadata?.git?.remote_url, commitId)

            return (
                <ExternalCellLink
                    to={commitLink}
                    tooltip="Open commit"
                    label={commitId ? commitId.substring(0, 7) : '-'}
                />
            )
        },
    },
    {
        id: 'branch',
        header: 'Branch',
        cell: ({ row }) => {
            const git = row.original.metadata?.git
            const branchLink = GitMetadataParser.getBranchLink(git?.remote_url, git?.branch)

            return <ExternalCellLink to={branchLink} tooltip="Open branch" label={git?.branch ?? '-'} />
        },
    },
    {
        id: 'repository',
        header: 'Repository',
        cell: ({ row }) => {
            const git = row.original.metadata?.git
            const repoLink = GitMetadataParser.getRepoLink(git?.remote_url)

            return <ExternalCellLink to={repoLink} tooltip="Open repository" label={git?.repo_name ?? '-'} />
        },
    },
    {
        id: 'created_at',
        header: 'Created at',
        cell: ({ row }) => humanFriendlyDetailedTime(row.original.created_at),
    },
]

export function QuillReleases(): JSX.Element {
    const { pagination, releases, releaseResponseLoading } = useValues(releasesLogic)
    const { setPage } = useActions(releasesLogic)

    const pageCount = Math.ceil(pagination.entryCount / pagination.pageSize)

    const initialLoading = releaseResponseLoading && releases.length === 0

    return (
        <div className="flex flex-col gap-2">
            <Text size="xs" render={<p className="m-0" />}>
                Releases are versions of your application that have been deployed. They are automatically created when
                you upload sourcemaps to PostHog.
            </Text>
            <Text size="xs" render={<p className="m-0" />}>
                Each release can include git metadata such as the commit SHA, branch, and repository URL, which helps
                you track down the source of errors.
            </Text>
            {initialLoading ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                </div>
            ) : (
                <div
                    className={cn('transition-opacity', releaseResponseLoading && 'opacity-60')}
                    aria-busy={releaseResponseLoading}
                >
                    <DataTable
                        columns={COLUMNS}
                        data={releases}
                        fullWidth
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyTitle>No releases found</EmptyTitle>
                                    <EmptyDescription>
                                        Releases are automatically created when PostHog detects version information in
                                        your error tracking data. Learn more in the{' '}
                                        <Button
                                            variant="link"
                                            size="inline"
                                            nativeButton={false}
                                            render={
                                                <LinkPrimitive
                                                    to="https://posthog.com/docs/error-tracking"
                                                    target="_blank"
                                                />
                                            }
                                        >
                                            docs
                                        </Button>
                                        .
                                    </EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        }
                    />
                </div>
            )}
            {pageCount > 1 && (
                <QuillTablePagination
                    currentPage={pagination.currentPage}
                    pageCount={pageCount}
                    pageSize={pagination.pageSize}
                    total={pagination.entryCount}
                    onPageChange={setPage}
                />
            )}
        </div>
    )
}
