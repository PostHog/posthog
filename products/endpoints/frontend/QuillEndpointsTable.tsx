import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCopy, IconEndpoints, IconRefresh, IconSearch } from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    Badge,
    Button,
    DataTable,
    type DataTableProps,
    DropdownMenu,
    DropdownMenuContent,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    FilterClearItem,
    FilterMenuTrigger,
    IconStack,
    IconStackItem,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Skeleton,
    Text,
} from '@posthog/quill'

import { QuillTagsFilterSubMenu } from 'lib/components/QuillTagsFilterSubMenu'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { EndpointType, UserBasicType } from '~/types'

import { humanizeQueryKind } from './common'
import { EndpointFromInsightModal } from './EndpointFromInsightModal'
import { endpointLogic } from './endpointLogic'
import { endpointsLogic } from './endpointsLogic'
import { QuillEndpointActionsMenu } from './QuillEndpointActionsMenu'

const PAGE_SIZE = 20

function creatorName(user: UserBasicType | null | undefined): string {
    if (!user) {
        return ''
    }
    const name = fullName(user)
    return name && name !== 'Unknown User' ? name : user.email
}

function initials(name: string): string {
    return name
        .split(/[\s@._-]+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase() ?? '')
        .join('')
}

function TimestampCell({ value, never }: { value: string | null | undefined; never: string }): JSX.Element {
    return value ? (
        <span className="whitespace-nowrap">
            <TZLabel time={value} />
        </span>
    ) : (
        <Text size="xs" variant="muted" render={<span />}>
            {never}
        </Text>
    )
}

// TanStack renders cell functions as components, so their identity must survive re-renders.
const columns: DataTableProps<EndpointType, unknown>['columns'] = [
    {
        accessorKey: 'name',
        header: 'Name',
        meta: { expand: true },
        cell: ({ row }) => {
            const endpoint = row.original
            return (
                <div className="flex min-w-0 flex-col items-start gap-0.5">
                    <span className="flex items-center gap-2">
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
                    </span>
                    {endpoint.description && (
                        <Text
                            size="xs"
                            variant="muted"
                            render={<span />}
                            className="line-clamp-1 max-w-md break-all px-2"
                            title={endpoint.description}
                        >
                            {endpoint.description}
                        </Text>
                    )}
                </div>
            )
        },
    },
    {
        accessorKey: 'tags',
        header: 'Tags',
        enableSorting: false,
        cell: ({ row }) => {
            const tags = row.original.tags ?? []
            return tags.length > 0 ? (
                <span className="flex flex-wrap gap-1">
                    {[...tags].sort().map((tag) => (
                        <Badge key={tag}>{tag}</Badge>
                    ))}
                </span>
            ) : null
        },
    },
    {
        accessorKey: 'created_at',
        header: 'Created',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ getValue }) => <TimestampCell value={getValue<string | null>()} never="Unknown" />,
    },
    {
        id: 'created_by',
        accessorFn: (endpoint) => creatorName(endpoint.created_by),
        header: 'Created by',
        cell: ({ getValue }) => {
            const name = getValue<string>()
            return name ? (
                <span className="flex items-center gap-2">
                    <Avatar size="xs">
                        <AvatarFallback>{initials(name)}</AvatarFallback>
                    </Avatar>
                    <Text size="xs" render={<span />} className="truncate">
                        {name}
                    </Text>
                </span>
            ) : (
                <Text size="xs" variant="muted" render={<span />}>
                    Unknown
                </Text>
            )
        },
    },
    {
        id: 'last_executed_at',
        accessorFn: (endpoint) => endpoint.last_executed_at ?? '',
        header: 'Last executed',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ row }) => <TimestampCell value={row.original.last_executed_at} never="Never" />,
    },
    {
        id: 'last_materialized_at',
        accessorFn: (endpoint) => endpoint.materialization?.last_materialized_at ?? '',
        header: 'Last materialized',
        sortDescFirst: true,
        meta: { align: 'right' },
        cell: ({ row }) => <TimestampCell value={row.original.materialization?.last_materialized_at} never="Never" />,
    },
    {
        accessorKey: 'endpoint_path',
        header: 'Endpoint path',
        enableSorting: false,
        cell: ({ row }) => (
            <Button
                variant="outline"
                size="sm"
                className="max-w-72 font-mono"
                onClick={() => void copyToClipboard(row.original.endpoint_path, 'endpoint URL')}
                data-attr="endpoint-copy-path"
            >
                <IconCopy />
                <span className="truncate">{row.original.endpoint_path}</span>
            </Button>
        ),
    },
    {
        id: 'is_active',
        accessorFn: (endpoint) => Number(endpoint.is_active),
        header: 'Status',
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
        header: '',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => <QuillEndpointActionsMenu endpoint={row.original} />,
    },
]

export function QuillEndpointsTable(): JSX.Element {
    const { endpoints, allEndpointsLoading, filters } = useValues(endpointsLogic)
    const { setFilters, loadEndpoints } = useActions(endpointsLogic)
    const { duplicateEndpoint } = useValues(endpointLogic)

    // The most recently executed endpoints come first until a header is clicked.
    const rows = useMemo(
        () => [...endpoints].sort((a, b) => (b.last_executed_at ?? '').localeCompare(a.last_executed_at ?? '')),
        [endpoints]
    )
    const tagsActive = filters.tags.length > 0
    const showSkeleton = allEndpointsLoading && endpoints.length === 0

    return (
        <div className="flex flex-col gap-2" data-attr="endpoints-table">
            <div className="flex flex-wrap items-center gap-2">
                <InputGroup size="sm" className="w-64 max-w-full">
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
                        onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
                            setFilters({ search: event.target.value })
                        }
                        data-attr="endpoints-search"
                    />
                </InputGroup>
                <DropdownMenu>
                    <FilterMenuTrigger active={tagsActive} dataAttr="endpoints-tag-filter" />
                    <DropdownMenuContent align="start" className="min-w-64">
                        <QuillTagsFilterSubMenu
                            logicKey="endpoints-list"
                            selected={filters.tags}
                            onChange={(tags) => setFilters({ tags })}
                            dataAttr="endpoints-tag-filter-tags"
                            optionDataAttr="endpoints-tag-filter-tag"
                        />
                        <FilterClearItem
                            active={tagsActive}
                            onClear={() => setFilters({ tags: [] })}
                            dataAttr="endpoints-tag-filter-clear"
                        />
                    </DropdownMenuContent>
                </DropdownMenu>
                <Button
                    variant="outline"
                    className="ml-auto"
                    onClick={() => loadEndpoints()}
                    loading={allEndpointsLoading}
                    data-attr="endpoints-reload"
                >
                    <IconRefresh />
                    Reload
                </Button>
            </div>
            {showSkeleton ? (
                <div className="flex flex-col gap-3" role="status">
                    <span className="sr-only">Loading endpoints</span>
                    {[0, 1, 2, 3, 4].map((index) => (
                        <Skeleton key={index} className="h-8 w-full" />
                    ))}
                </div>
            ) : (
                <DataTable
                    columns={columns}
                    data={rows}
                    fullWidth
                    pageSize={PAGE_SIZE}
                    rowClassName={(endpoint) => (endpoint._highlight ? 'bg-fill-selected' : undefined)}
                    empty={
                        <Empty>
                            <EmptyHeader>
                                <IconStack>
                                    <IconStackItem color="var(--color-product-endpoints-light)">
                                        <IconEndpoints />
                                    </IconStackItem>
                                </IconStack>
                                <EmptyTitle>No endpoints match your filters</EmptyTitle>
                                <EmptyDescription>Change the search or clear the tag filter.</EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    }
                />
            )}
            {duplicateEndpoint && (
                <EndpointFromInsightModal
                    insightQuery={duplicateEndpoint.query}
                    insightShortId={duplicateEndpoint.derived_from_insight ?? undefined}
                />
            )}
        </div>
    )
}
