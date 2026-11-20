import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconDownload, IconSearch, IconTrash, IconWarning } from '@posthog/icons'
import {
    Button,
    DataTable,
    DataTableProps,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Skeleton,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { ErrorTrackingSymbolSet, SymbolSetStatusFilter } from 'lib/components/Errors/types'
import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { QuillReleasePreviewPill } from 'products/error_tracking/frontend/components/ReleasesPreview/QuillReleasePreviewPill'
import { errorTrackingEditAccessDisabledReason } from 'products/error_tracking/frontend/utils'

import { confirmBulkDeleteSymbolSets, confirmDeleteSymbolSet } from './symbolSetDialogs'
import { RESULTS_PER_PAGE, SymbolSetOrder, symbolSetLogic } from './symbolSetLogic'

const STATUS_FILTER_OPTIONS: { value: SymbolSetStatusFilter; label: string; icon?: JSX.Element }[] = [
    { value: 'valid', label: 'Valid', icon: <IconCheckCircle /> },
    { value: 'invalid', label: 'Invalid', icon: <IconWarning /> },
    { value: 'all', label: 'All' },
]

export function QuillSymbolSets(): JSX.Element {
    const {
        symbolSetStatusFilter,
        searchQuery,
        selectedSymbolSetIds,
        deleteSymbolSetResponseLoading,
        page,
        symbolSetResponse,
        symbolSetResponseLoading,
        symbolSetOrder,
    } = useValues(symbolSetLogic)
    const {
        setSymbolSetStatusFilter,
        setSearchQuery,
        bulkDeleteSymbolSets,
        deleteSymbolSet,
        downloadSymbolSet,
        setSymbolSetOrder,
        setSelectedSymbolSetIds,
        setPage,
    } = useActions(symbolSetLogic)

    const symbolSets = symbolSetResponse?.results || []
    const entryCount = symbolSetResponse?.count ?? 0
    const pageCount = Math.ceil(entryCount / RESULTS_PER_PAGE)
    const tableLoading = symbolSetResponseLoading || deleteSymbolSetResponseLoading
    const editDisabledReason = errorTrackingEditAccessDisabledReason() ?? undefined
    const descending = symbolSetOrder.startsWith('-')
    const sortColumn = descending ? symbolSetOrder.slice(1) : symbolSetOrder

    const columns: DataTableProps<ErrorTrackingSymbolSet, unknown>['columns'] = [
        {
            id: 'ref',
            header: 'Reference',
            enableSorting: false,
            cell: ({ row }) => (
                <div className="max-w-50 truncate rtl" title={row.original.ref} translate="no">
                    {row.original.ref}
                </div>
            ),
        },
        {
            id: 'release',
            header: 'Release',
            enableSorting: false,
            cell: ({ row }) =>
                row.original.release ? <QuillReleasePreviewPill release={row.original.release} /> : '-',
        },
        {
            id: 'status',
            header: 'Status',
            enableSorting: false,
            cell: ({ row }) => {
                const { failure_reason, has_uploaded_file } = row.original
                const statusTooltip =
                    failure_reason || (!has_uploaded_file ? 'No source map file has been uploaded' : undefined)
                const status = !has_uploaded_file ? (
                    <span className="inline-flex items-center gap-1 text-destructive-foreground">
                        <IconWarning /> Missing
                    </span>
                ) : (
                    <span className="inline-flex items-center gap-1 text-success-foreground">
                        <IconCheckCircle /> Uploaded
                    </span>
                )

                if (!statusTooltip) {
                    return status
                }

                return (
                    <Tooltip>
                        <TooltipTrigger render={status} />
                        <TooltipContent className="max-w-80">{statusTooltip}</TooltipContent>
                    </Tooltip>
                )
            },
        },
        {
            accessorKey: 'last_used',
            header: 'Last Used',
            cell: ({ row }) => (row.original.last_used ? humanFriendlyDetailedTime(row.original.last_used) : '-'),
        },
        {
            accessorKey: 'created_at',
            header: 'Created At',
            cell: ({ row }) => humanFriendlyDetailedTime(row.original.created_at),
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            cell: ({ row }) => {
                const { id, has_uploaded_file } = row.original

                return (
                    <div className="flex items-center justify-end gap-1">
                        {has_uploaded_file && (
                            <Button
                                size="icon-sm"
                                aria-label="Download source map"
                                tooltip="Download source map"
                                onClick={() => downloadSymbolSet(id)}
                            >
                                <IconDownload />
                            </Button>
                        )}
                        <Button
                            size="icon-sm"
                            aria-label="Delete symbol set"
                            tooltip="Delete symbol set"
                            disabledReason={editDisabledReason}
                            onClick={() => confirmDeleteSymbolSet(() => deleteSymbolSet(id))}
                        >
                            <IconTrash />
                        </Button>
                    </div>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <Text size="xs" render={<p className="m-0" />}>
                Source maps are required to demangle any minified code in your exception stack traces. PostHog
                automatically retrieves source maps where possible.
            </Text>
            <Text size="xs" render={<p className="m-0" />}>
                Cases where it was not possible are listed below. Source maps can be uploaded retroactively but changes
                will only apply to all future exceptions ingested.
            </Text>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <InputGroup size="sm" className="w-90 max-w-full">
                        <InputGroupAddon align="inline-start">
                            <IconSearch />
                        </InputGroupAddon>
                        <InputGroupInput
                            type="search"
                            placeholder="Search by reference, release, version, or commit"
                            aria-label="Search symbol sets"
                            value={searchQuery}
                            onChange={(event) => setSearchQuery(event.target.value)}
                        />
                    </InputGroup>
                    {selectedSymbolSetIds.length > 0 && (
                        <>
                            <Button
                                variant="destructive-outline"
                                loading={deleteSymbolSetResponseLoading}
                                disabledReason={editDisabledReason}
                                onClick={() =>
                                    confirmBulkDeleteSymbolSets(selectedSymbolSetIds.length, () =>
                                        bulkDeleteSymbolSets()
                                    )
                                }
                            >
                                <IconTrash />
                                Delete
                            </Button>
                            <Text size="sm" weight="medium" render={<span className="m-0" />}>
                                <span translate="no">{selectedSymbolSetIds.length}</span>
                                <span> selected</span>
                            </Text>
                        </>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    <Text size="xs" render={<span className="m-0" />}>
                        Status:
                    </Text>
                    <ToggleGroup
                        variant="outline"
                        aria-label="Status"
                        value={[symbolSetStatusFilter]}
                        onValueChange={(next: string[]) => {
                            const picked = next[0] as SymbolSetStatusFilter | undefined
                            if (picked) {
                                setSymbolSetStatusFilter(picked)
                            }
                        }}
                    >
                        {STATUS_FILTER_OPTIONS.map((option) =>
                            option.icon ? (
                                <Tooltip key={option.value}>
                                    <TooltipTrigger
                                        delay={0}
                                        render={<ToggleGroupItem value={option.value} aria-label={option.label} />}
                                    >
                                        {option.icon}
                                    </TooltipTrigger>
                                    <TooltipContent>{option.label}</TooltipContent>
                                </Tooltip>
                            ) : (
                                <ToggleGroupItem key={option.value} value={option.value}>
                                    {option.label}
                                </ToggleGroupItem>
                            )
                        )}
                    </ToggleGroup>
                </div>
            </div>
            {tableLoading && symbolSets.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                </div>
            ) : (
                <div className={cn('transition-opacity', tableLoading && 'opacity-60')} aria-busy={tableLoading}>
                    <DataTable
                        columns={columns}
                        data={symbolSets}
                        fullWidth
                        selectable
                        getRowId={(symbolSet) => symbolSet.id}
                        rowSelection={Object.fromEntries(selectedSymbolSetIds.map((id: string) => [id, true]))}
                        onRowSelectionChange={(rowSelection) =>
                            setSelectedSymbolSetIds(Object.keys(rowSelection).filter((id) => rowSelection[id]))
                        }
                        sorting={[{ id: sortColumn, desc: descending }]}
                        onSortingChange={([sort]) => {
                            // The table never shows an unsorted state, so a click that would clear the sort flips it.
                            if (!sort) {
                                setSymbolSetOrder((descending ? sortColumn : `-${sortColumn}`) as SymbolSetOrder)
                                return
                            }
                            setSymbolSetOrder(`${sort.desc ? '-' : ''}${sort.id}` as SymbolSetOrder)
                        }}
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyTitle>No symbol sets found</EmptyTitle>
                                    <EmptyDescription>
                                        Learn how to upload them from the{' '}
                                        <Button
                                            variant="link"
                                            size="inline"
                                            nativeButton={false}
                                            render={
                                                <LinkPrimitive to="https://posthog.com/docs/error-tracking/upload-source-maps" />
                                            }
                                        >
                                            docs
                                        </Button>
                                    </EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        }
                    />
                </div>
            )}
            {pageCount > 1 && (
                <QuillTablePagination
                    currentPage={page}
                    pageCount={pageCount}
                    pageSize={RESULTS_PER_PAGE}
                    total={entryCount}
                    onPageChange={setPage}
                />
            )}
        </div>
    )
}
