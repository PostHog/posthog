import { IconFolder, IconGithub } from '@posthog/icons'
import type { DataTableProps } from '@posthog/quill-components'
import { DataTable } from '@posthog/quill-components'
import {
    Avatar,
    AvatarFallback,
    Button,
    Card,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill-primitives'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardGithubRepositoryUrl, wizardWorkspaceLabel } from '../wizardRunDisplay'
import { WizardRunActionsMenu } from './WizardRunActionsMenu'
import { WizardRunEnvironmentTag } from './WizardRunEnvironmentTag'
import { WizardRunsEmptyState } from './WizardRunsEmptyState'
import { WizardRunStatusTag } from './WizardRunStatusTag'

export function WizardRunTable({
    runs,
    totalRuns,
    currentUserId,
    loading,
    failed,
    hasActiveFilters,
    refreshing,
    cancelling,
    onOpenLibrary,
    onClearFilters,
    onRefreshRuns,
    onSelect,
    onRefreshRun,
    onCopyRunId,
    onCancel,
}: {
    runs: WizardRunApi[]
    totalRuns: number
    currentUserId: number | null
    loading: boolean
    failed: boolean
    hasActiveFilters: boolean
    refreshing: boolean
    cancelling: boolean
    onOpenLibrary: () => void
    onClearFilters: () => void
    onRefreshRuns: () => void
    onSelect: (run: WizardRunApi) => void
    onRefreshRun: (run: WizardRunApi) => void
    onCopyRunId: (runId: string) => void
    onCancel: (run: WizardRunApi) => void
}): JSX.Element {
    const columns: DataTableProps<WizardRunApi, unknown>['columns'] = [
        {
            accessorKey: 'program.name',
            header: 'Program',
            cell: ({ row }) => {
                const run = row.original
                return (
                    <Button variant="link-muted" size="sm" onClick={() => onSelect(run)}>
                        <span className="flex min-w-44 flex-col items-start text-left">
                            <span className="font-semibold">{run.program.name}</span>
                            <Text size="xs" variant="muted">
                                Wizard {run.program.wizard_version}
                            </Text>
                        </span>
                    </Button>
                )
            },
        },
        {
            id: 'workspace',
            header: 'Workspace',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row }) => {
                const run = row.original
                if (run.workspace.type === 'git_repository') {
                    return (
                        <Button
                            variant="link-muted"
                            size="sm"
                            render={
                                <LinkPrimitive
                                    to={wizardGithubRepositoryUrl(run.workspace.repository)}
                                    target="_blank"
                                    onClick={(event) => event.stopPropagation()}
                                />
                            }
                        >
                            <IconGithub />
                            {run.workspace.repository}
                        </Button>
                    )
                }
                return (
                    <Text size="sm" className="flex items-center gap-1">
                        <IconFolder />
                        {wizardWorkspaceLabel(run)}
                    </Text>
                )
            },
        },
        {
            id: 'created_by',
            accessorFn: (run) => run.created_by?.first_name || run.created_by?.email || '',
            header: 'Created by',
            cell: ({ row }) => {
                const creator = row.original.created_by
                if (!creator) {
                    return (
                        <Text size="sm" variant="muted">
                            Unknown
                        </Text>
                    )
                }

                const name = [creator.first_name, creator.last_name].filter(Boolean).join(' ') || creator.email
                const initials = creator.first_name
                    ? `${creator.first_name[0]}${creator.last_name[0] ?? ''}`
                    : creator.email[0]

                return (
                    <span className="flex min-w-0 items-center gap-2">
                        <Avatar size="sm">
                            <AvatarFallback>{initials}</AvatarFallback>
                        </Avatar>
                        <Text size="sm" className="max-w-40 truncate">
                            {name}
                        </Text>
                    </span>
                )
            },
        },
        {
            accessorKey: 'environment',
            header: 'Environment',
            cell: ({ row }) => <WizardRunEnvironmentTag environment={row.original.environment} />,
        },
        {
            accessorKey: 'status',
            header: 'Status',
            cell: ({ row }) => {
                const run = row.original
                return <WizardRunStatusTag status={run.status} />
            },
        },
        {
            accessorKey: 'started_at',
            header: 'Started',
            cell: ({ row }) =>
                row.original.started_at ? (
                    <TZLabel time={row.original.started_at} className="whitespace-nowrap text-xs" />
                ) : (
                    <Text size="xs" variant="muted">
                        Not started
                    </Text>
                ),
        },
        {
            id: 'actions',
            header: () => <span className="sr-only">Actions</span>,
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) => (
                <WizardRunActionsMenu
                    run={row.original}
                    currentUserId={currentUserId}
                    refreshing={refreshing}
                    cancelling={cancelling}
                    onView={onSelect}
                    onRefresh={onRefreshRun}
                    onCopyRunId={onCopyRunId}
                    onCancel={onCancel}
                />
            ),
        },
    ]

    if (failed && totalRuns === 0) {
        return (
            <Item tone="destructive" variant="outline">
                <ItemContent>
                    <ItemTitle>Couldn’t load Wizard runs</ItemTitle>
                    <ItemDescription>Refresh the page and try again.</ItemDescription>
                </ItemContent>
                <Button variant="outline" size="sm" onClick={onRefreshRuns}>
                    Refresh
                </Button>
            </Item>
        )
    }

    const empty = hasActiveFilters ? (
        <Empty className="min-h-64 py-12">
            <EmptyHeader>
                <EmptyTitle>No matching Wizard runs</EmptyTitle>
                <EmptyDescription>Try another search or clear the current filters.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button variant="outline" onClick={onClearFilters}>
                    Clear filters
                </Button>
            </EmptyContent>
        </Empty>
    ) : (
        <WizardRunsEmptyState onOpenLibrary={onOpenLibrary} />
    )

    return (
        <div className="flex flex-col gap-2">
            {failed && totalRuns > 0 && (
                <Item tone="warning" variant="outline">
                    <ItemContent>Live updates stopped. The list may be out of date.</ItemContent>
                    <Button variant="outline" size="sm" onClick={onRefreshRuns}>
                        Refresh
                    </Button>
                </Item>
            )}
            {loading ? (
                <div className="flex flex-col gap-2">
                    {Array.from({ length: 7 }).map((_, index) => (
                        <Skeleton key={index} className="h-[68px] w-full" />
                    ))}
                </div>
            ) : (
                <Card size="sm" flush className="overflow-hidden">
                    <DataTable
                        columns={columns}
                        data={runs}
                        empty={empty}
                        pageSize={25}
                        fullWidth
                        onRowClick={onSelect}
                    />
                </Card>
            )}
        </div>
    )
}
