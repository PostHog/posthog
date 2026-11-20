import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconEllipsis, IconRefresh, IconSearch, IconX } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Badge,
    Button,
    Card,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    FilterClearItem,
    FilterMenuTrigger,
    FilterSearchSubMenu,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupInput,
    InputGroupText,
    Skeleton,
    Text,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, EndpointType } from '~/types'

import { duplicateEndpointFromList, humanizeQueryKind } from './common'
import { EndpointFromInsightModal } from './EndpointFromInsightModal'
import { endpointLogic } from './endpointLogic'
import { endpointsLogic } from './endpointsLogic'

// Rows that never ran sort after the ones that did, like the Lemon table's default order.
function byLastExecutedDesc(a: EndpointType, b: EndpointType): number {
    return (b.last_executed_at ?? '').localeCompare(a.last_executed_at ?? '')
}

function EndpointsSearch(): JSX.Element {
    const { filters } = useValues(endpointsLogic)
    const { setFilters } = useActions(endpointsLogic)

    return (
        <InputGroup size="sm" className="w-56 max-w-full">
            <InputGroupAddon align="inline-start">
                <InputGroupText>
                    <IconSearch />
                </InputGroupText>
            </InputGroupAddon>
            <InputGroupInput
                type="search"
                aria-label="Search for endpoints"
                placeholder="Search for endpoints"
                value={filters.search}
                onChange={(event: React.ChangeEvent<HTMLInputElement>) => setFilters({ search: event.target.value })}
                // The browser's own clear button would sit next to this one.
                className="[&::-webkit-search-cancel-button]:hidden"
                data-attr="endpoints-search"
            />
            {filters.search !== '' && (
                <InputGroupAddon align="inline-end">
                    <InputGroupButton
                        size="icon-xs"
                        aria-label="Clear search"
                        onClick={() => setFilters({ search: '' })}
                    >
                        <IconX />
                    </InputGroupButton>
                </InputGroupAddon>
            )}
        </InputGroup>
    )
}

function EndpointsFilterMenu(): JSX.Element {
    const { filters, availableTags } = useValues(endpointsLogic)
    const { setFilters } = useActions(endpointsLogic)
    const active = filters.tags.length > 0

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={active} dataAttr="endpoints-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
                <FilterSearchSubMenu
                    label="Tags"
                    allLabel="Any tag"
                    pluralNoun="tags"
                    options={availableTags.map((tag) => ({ value: tag, label: tag }))}
                    selected={filters.tags}
                    onChange={(tags) => setFilters({ tags })}
                    searchPlaceholder="Search tags"
                    emptyText="No matching tags"
                    dataAttr="endpoints-tag-filter"
                    optionDataAttr="endpoints-tag-filter-option"
                />
                <FilterClearItem active={active} onClear={() => setFilters({ tags: [] })} />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function EndpointNameCell({ endpoint }: { endpoint: EndpointType }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col items-start">
            <div className="flex flex-wrap items-center gap-1">
                <Button
                    variant="link-foreground"
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.endpoint(endpoint.name)} />}
                    data-attr="endpoint-name-link"
                >
                    {endpoint.name}
                </Button>
                {endpoint.query?.kind && <Badge>{humanizeQueryKind(endpoint.query.kind)}</Badge>}
            </div>
            {endpoint.description && (
                <Text
                    size="xs"
                    variant="muted"
                    className="line-clamp-1 max-w-120 break-all"
                    title={endpoint.description}
                >
                    {endpoint.description}
                </Text>
            )}
        </div>
    )
}

function EndpointActionsMenu({
    endpoint,
    onDelete,
}: {
    endpoint: EndpointType
    onDelete: (name: string) => void
}): JSX.Element {
    const { confirmToggleActive, setDuplicateEndpoint } = useActions(endpointLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="default"
                        size="icon-sm"
                        aria-label={`Actions for ${endpoint.name}`}
                        tooltip="Actions"
                        data-attr="endpoint-actions"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem
                    onClick={() => router.actions.push(urls.endpointsUsage({ endpointFilter: [endpoint.name] }))}
                >
                    View usage
                </DropdownMenuItem>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Endpoint}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <DropdownMenuItem onClick={() => duplicateEndpointFromList(endpoint, setDuplicateEndpoint)}>
                        Duplicate endpoint
                    </DropdownMenuItem>
                </AccessControlAction>
                <DropdownMenuSeparator />
                <AccessControlAction
                    resourceType={AccessControlResourceType.Endpoint}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <DropdownMenuItem onClick={() => confirmToggleActive(endpoint)} data-attr="endpoint-activate">
                        {endpoint.is_active ? 'Deactivate endpoint' : 'Activate endpoint'}
                    </DropdownMenuItem>
                </AccessControlAction>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Endpoint}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <DropdownMenuItem variant="destructive" onClick={() => onDelete(endpoint.name)}>
                        Delete endpoint
                    </DropdownMenuItem>
                </AccessControlAction>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function DeleteEndpointDialog({
    endpointName,
    onClose,
}: {
    endpointName: string | null
    onClose: () => void
}): JSX.Element {
    const { deleteEndpoint } = useActions(endpointLogic)

    return (
        <AlertDialog open={endpointName !== null} onOpenChange={(open: boolean) => !open && onClose()}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Delete endpoint?</AlertDialogTitle>
                    <AlertDialogDescription>
                        Are you sure you want to delete this endpoint? This action cannot be undone.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <Button
                        variant="destructive-outline"
                        onClick={() => {
                            if (endpointName) {
                                deleteEndpoint(endpointName)
                            }
                            onClose()
                        }}
                        data-attr="endpoint-delete-confirm"
                    >
                        Delete
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}

export function QuillEndpoints(): JSX.Element {
    const { endpoints, allEndpoints, allEndpointsLoading, filters } = useValues(endpointsLogic)
    const { setFilters, loadEndpoints } = useActions(endpointsLogic)
    const { duplicateEndpoint } = useValues(endpointLogic)
    const [endpointToDelete, setEndpointToDelete] = useState<string | null>(null)

    const sortedEndpoints = useMemo(() => [...endpoints].sort(byLastExecutedDesc), [endpoints])

    const columns = useMemo<ColumnDef<EndpointType>[]>(
        () => [
            {
                id: 'name',
                header: 'Name',
                accessorFn: (endpoint) => endpoint.name.toLowerCase(),
                meta: { expand: true },
                cell: ({ row }) => <EndpointNameCell endpoint={row.original} />,
            },
            {
                id: 'tags',
                header: 'Tags',
                enableSorting: false,
                cell: ({ row }) =>
                    row.original.tags && row.original.tags.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                            {[...row.original.tags].sort().map((tag) => (
                                <Badge key={tag}>{tag}</Badge>
                            ))}
                        </div>
                    ) : null,
            },
            {
                id: 'created_at',
                header: 'Created at',
                accessorFn: (endpoint) => endpoint.created_at ?? '',
                cell: ({ row }) => (row.original.created_at ? <TZLabel time={row.original.created_at} /> : null),
            },
            {
                id: 'created_by',
                header: 'Created by',
                accessorFn: (endpoint) => endpoint.created_by?.first_name || endpoint.created_by?.email || '',
                cell: ({ row }) =>
                    row.original.created_by ? (
                        <ProfilePicture user={row.original.created_by} size="md" showName />
                    ) : (
                        <Text variant="muted">—</Text>
                    ),
            },
            {
                id: 'last_executed_at',
                header: 'Last executed at',
                accessorFn: (endpoint) => endpoint.last_executed_at ?? '',
                cell: ({ row }) =>
                    row.original.last_executed_at ? (
                        <TZLabel time={row.original.last_executed_at} />
                    ) : (
                        <Text variant="muted">Never</Text>
                    ),
            },
            {
                id: 'last_materialized_at',
                header: 'Last materialized at',
                accessorFn: (endpoint) => endpoint.materialization?.last_materialized_at ?? '',
                cell: ({ row }) => {
                    const lastMaterializedAt = row.original.materialization?.last_materialized_at
                    return lastMaterializedAt ? <TZLabel time={lastMaterializedAt} /> : null
                },
            },
            {
                id: 'endpoint_path',
                header: 'Endpoint path',
                enableSorting: false,
                cell: ({ row }) => (
                    <Button
                        variant="outline"
                        size="xs"
                        className="font-mono"
                        tooltip="Copy endpoint URL"
                        onClick={() => void copyToClipboard(row.original.endpoint_path, 'endpoint URL')}
                    >
                        {row.original.endpoint_path}
                    </Button>
                ),
            },
            {
                id: 'is_active',
                header: 'Status',
                accessorFn: (endpoint) => Number(endpoint.is_active),
                sortDescFirst: true,
                meta: { align: 'center' },
                cell: ({ row }) =>
                    row.original.is_active ? (
                        <Badge variant="success">Active</Badge>
                    ) : (
                        <Badge variant="destructive">Inactive</Badge>
                    ),
            },
            {
                id: 'actions',
                header: () => <span className="sr-only">Actions</span>,
                enableSorting: false,
                enableResizing: false,
                cell: ({ row }) => <EndpointActionsMenu endpoint={row.original} onDelete={setEndpointToDelete} />,
            },
        ],
        []
    )

    const filtersActive = filters.search !== '' || filters.tags.length > 0

    return (
        <div className="flex flex-col gap-4" data-quill>
            <div className="flex flex-wrap items-center gap-2">
                <EndpointsSearch />
                <EndpointsFilterMenu />
                <Button
                    variant="outline"
                    size="icon"
                    className="ml-auto"
                    aria-label="Reload endpoints"
                    tooltip="Reload endpoints"
                    onClick={() => loadEndpoints()}
                    loading={allEndpointsLoading}
                    data-attr="endpoints-reload"
                >
                    <IconRefresh />
                </Button>
            </div>
            {allEndpointsLoading && allEndpoints.length === 0 ? (
                <Skeleton className="h-64 w-full" />
            ) : (
                <Card size="sm" flush className="pt-0" data-attr="endpoints-table">
                    <DataTable
                        columns={columns}
                        data={sortedEndpoints}
                        pageSize={20}
                        fullWidth
                        size="sm"
                        getRowId={(endpoint) => String(endpoint.id)}
                        empty={
                            <div className="flex flex-col items-center gap-2 py-4">
                                <Text variant="muted">No endpoints matching your filters!</Text>
                                {filtersActive && (
                                    <Button
                                        variant="outline"
                                        onClick={() => setFilters({ search: '', tags: [] })}
                                        data-attr="endpoints-clear-filters"
                                    >
                                        Clear filters
                                    </Button>
                                )}
                            </div>
                        }
                    />
                </Card>
            )}
            <DeleteEndpointDialog endpointName={endpointToDelete} onClose={() => setEndpointToDelete(null)} />
            {duplicateEndpoint && (
                <EndpointFromInsightModal
                    insightQuery={duplicateEndpoint.query}
                    insightShortId={duplicateEndpoint.derived_from_insight ?? undefined}
                />
            )}
        </div>
    )
}
