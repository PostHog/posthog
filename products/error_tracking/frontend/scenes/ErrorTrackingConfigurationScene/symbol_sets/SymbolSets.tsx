import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { P, match } from 'ts-pattern'

import { IconCheckCircle, IconDownload, IconSort, IconTrash, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDialog,
    LemonInput,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    LemonTable,
    LemonTableColumns,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { ErrorTrackingSymbolSet, SymbolSetStatusFilter } from 'lib/components/Errors/types'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { pluralize } from 'lib/utils/strings'

import { ReleasePreviewPill } from 'products/error_tracking/frontend/components/ReleasesPreview/ReleasePreviewPill'
import { errorTrackingEditAccessDisabledReason } from 'products/error_tracking/frontend/utils'

import { symbolSetFailureMessage } from './symbolSetFailure'
import { RESULTS_PER_PAGE, SymbolSetOrder, symbolSetLogic } from './symbolSetLogic'

const SYMBOL_SET_FILTER_OPTIONS: LemonSegmentedButtonOption<SymbolSetStatusFilter>[] = [
    {
        label: <IconCheckCircle />,
        value: 'valid',
        tooltip: 'Symbol sets with an uploaded file',
    },
    {
        label: <IconWarning />,
        value: 'invalid',
        tooltip: 'Symbol sets with no uploaded file',
    },
    {
        label: 'All',
        value: 'all',
        tooltip: 'All symbol sets',
    },
]

export function SymbolSets(): JSX.Element {
    const { symbolSetStatusFilter, searchQuery, selectedSymbolSetIds, deleteSymbolSetResponseLoading } =
        useValues(symbolSetLogic)
    const { loadSymbolSets, setSymbolSetStatusFilter, setSearchQuery, bulkDeleteSymbolSets } =
        useActions(symbolSetLogic)

    useEffect(() => {
        loadSymbolSets()
    }, [loadSymbolSets])

    return (
        <div className="deprecated-space-y-4">
            <p>
                Source maps are required to demangle any minified code in your exception stack traces. PostHog
                automatically retrieves source maps where possible.
            </p>

            <p>
                Cases where it was not possible are listed below. Source maps can be uploaded retroactively but changes
                will only apply to all future exceptions ingested.
            </p>
            <div className="space-y-2">
                <div className="flex justify-between items-center gap-2">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="search"
                            placeholder="Search by reference, release, version, or commit"
                            value={searchQuery}
                            onChange={setSearchQuery}
                            fullWidth
                            className="w-90"
                        />
                        {selectedSymbolSetIds.length > 0 && (
                            <>
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    size="small"
                                    icon={<IconTrash />}
                                    loading={deleteSymbolSetResponseLoading}
                                    disabledReason={errorTrackingEditAccessDisabledReason() ?? undefined}
                                    onClick={() =>
                                        LemonDialog.open({
                                            title: 'Delete symbol sets',
                                            description: `Are you sure you want to delete ${pluralize(selectedSymbolSetIds.length, 'symbol set', 'symbol sets')}?`,
                                            secondaryButton: {
                                                type: 'secondary',
                                                children: 'Cancel',
                                            },
                                            primaryButton: {
                                                type: 'primary',
                                                status: 'danger',
                                                onClick: () => bulkDeleteSymbolSets(),
                                                children: 'Delete',
                                            },
                                        })
                                    }
                                >
                                    Delete
                                </LemonButton>
                                <span className="text-sm font-medium">{selectedSymbolSetIds.length} selected</span>
                            </>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="mb-0">File:</span>
                        <LemonSegmentedButton
                            size="xsmall"
                            value={symbolSetStatusFilter}
                            options={SYMBOL_SET_FILTER_OPTIONS}
                            onChange={setSymbolSetStatusFilter}
                        />
                    </div>
                </div>
                <SymbolSetTable />
            </div>
        </div>
    )
}

const SymbolSetTable = (): JSX.Element => {
    const {
        page,
        symbolSetResponse,
        symbolSetResponseLoading,
        symbolSetOrder,
        selectedSymbolSetIds,
        deleteSymbolSetResponseLoading,
        shiftKeyHeld,
        previouslyCheckedIndex,
        symbolSetsLoadFailed,
    } = useValues(symbolSetLogic)
    const {
        loadSymbolSets,
        deleteSymbolSet,
        downloadSymbolSet,
        setSymbolSetOrder,
        setSelectedSymbolSetIds,
        setPreviouslyCheckedIndex,
        setPage,
    } = useActions(symbolSetLogic)

    // A failed load leaves the previous page of results in the loader value, so drop them and let
    // the empty state explain why the list is empty.
    const loadedResponse = symbolSetsLoadFailed ? null : symbolSetResponse
    const symbolSets = loadedResponse?.results || []
    const pagination = {
        controlled: true,
        pageSize: RESULTS_PER_PAGE,
        currentPage: page,
        entryCount: loadedResponse?.count ?? 0,
        onBackward: () => setPage(page - 1),
        onForward: () => setPage(page + 1),
    }

    const someSelected = selectedSymbolSetIds.length > 0 && selectedSymbolSetIds.length < symbolSets.length
    const allSelected = symbolSets.length > 0 && selectedSymbolSetIds.length === symbolSets.length

    const columns: LemonTableColumns<ErrorTrackingSymbolSet> = [
        {
            width: 32,
            title: (
                <LemonCheckbox
                    checked={allSelected ? true : someSelected ? 'indeterminate' : false}
                    onChange={() =>
                        allSelected || someSelected
                            ? setSelectedSymbolSetIds([])
                            : setSelectedSymbolSetIds(symbolSets.map((s: ErrorTrackingSymbolSet) => s.id))
                    }
                />
            ),
            render: (_, { id }, recordIndex) => {
                const checked = selectedSymbolSetIds.includes(id)
                return (
                    <LemonCheckbox
                        checked={checked}
                        onChange={(newValue) => {
                            const includedIds: string[] = []

                            if (!shiftKeyHeld || previouslyCheckedIndex === null) {
                                includedIds.push(id)
                            } else {
                                const start = Math.min(previouslyCheckedIndex, recordIndex)
                                const end = Math.max(previouslyCheckedIndex, recordIndex) + 1
                                includedIds.push(
                                    ...symbolSets.slice(start, end).map((s: ErrorTrackingSymbolSet) => s.id)
                                )
                            }

                            setPreviouslyCheckedIndex(recordIndex)
                            setSelectedSymbolSetIds(
                                newValue
                                    ? [...new Set([...selectedSymbolSetIds, ...includedIds])]
                                    : selectedSymbolSetIds.filter((i: string) => !includedIds.includes(i))
                            )
                        }}
                    />
                )
            },
        },
        {
            title: 'Reference',
            width: 200,
            render: (_, { ref }) => {
                return (
                    <div className="truncate w-100 overflow-hidden rtl py-0.5" title={ref}>
                        {ref}
                    </div>
                )
            },
        },
        {
            title: 'Release',
            render: (_, { release }) => {
                return release ? <ReleasePreviewPill release={release} /> : '-'
            },
        },
        {
            title: 'Status',
            render: (_, { failure_reason, has_uploaded_file }) => {
                const failureMessage = symbolSetFailureMessage(failure_reason)
                // Cymbal reads a stored failure reason before it reads the uploaded file, so a set
                // that has both is not usable yet, even though the file is there.
                const isFailed = has_uploaded_file && !!failureMessage

                if (!has_uploaded_file || isFailed) {
                    return (
                        <Tooltip title={failureMessage ?? 'No source map file has been uploaded'} placement="top">
                            <span className="text-danger cursor-pointer">
                                <IconWarning /> {isFailed ? 'Failed' : 'Missing'}
                            </span>
                        </Tooltip>
                    )
                }

                return (
                    <span className="text-success">
                        <IconCheckCircle /> Uploaded
                    </span>
                )
            },
        },
        {
            title: (
                <SortingHeaderColumn sortOrder={symbolSetOrder} setSortOrder={setSymbolSetOrder} columnKey="last_used">
                    Last Used
                </SortingHeaderColumn>
            ),
            dataIndex: 'last_used',
            render: (data) => (data ? humanFriendlyDetailedTime(data as string) : '-'),
        },
        {
            title: (
                <SortingHeaderColumn sortOrder={symbolSetOrder} setSortOrder={setSymbolSetOrder} columnKey="created_at">
                    Created At
                </SortingHeaderColumn>
            ),
            dataIndex: 'created_at',
            render: (data) => humanFriendlyDetailedTime(data as string),
        },
        {
            dataIndex: 'id',
            align: 'right',

            render: (_, { id, has_uploaded_file }) => {
                return (
                    <div className="flex justify-end items-center gap-1">
                        {has_uploaded_file && (
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                tooltip="Download source map"
                                icon={<IconDownload />}
                                onClick={() => downloadSymbolSet(id)}
                            />
                        )}
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            tooltip="Delete symbol set"
                            icon={<IconTrash />}
                            disabledReason={errorTrackingEditAccessDisabledReason() ?? undefined}
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Delete symbol set',
                                    description: 'Are you sure you want to delete this symbol set?',
                                    secondaryButton: {
                                        type: 'secondary',
                                        children: 'Cancel',
                                    },
                                    primaryButton: {
                                        type: 'primary',
                                        onClick: () => deleteSymbolSet(id),
                                        children: 'Delete',
                                    },
                                })
                            }
                        />
                    </div>
                )
            },
        },
    ]

    const emptyState = (
        <div className="flex flex-col justify-center items-center gap-2 p-4 text-center">
            {symbolSetsLoadFailed ? (
                <>
                    <div className="font-semibold">Couldn't load symbol sets</div>
                    <div className="text-secondary">The request to PostHog failed, so this list is empty.</div>
                    <LemonButton type="secondary" size="small" onClick={() => loadSymbolSets()}>
                        Try again
                    </LemonButton>
                </>
            ) : (
                <>
                    <div className="font-semibold">No symbol sets found</div>
                    <div className="text-secondary">
                        Learn how to upload them from the{' '}
                        <Link to="https://posthog.com/docs/error-tracking/upload-source-maps">docs</Link>
                    </div>
                </>
            )}
        </div>
    )

    return (
        <LemonTable
            id="symbol-sets"
            pagination={pagination}
            columns={columns}
            loading={symbolSetResponseLoading || deleteSymbolSetResponseLoading}
            dataSource={symbolSets}
            emptyState={!symbolSetResponseLoading && !deleteSymbolSetResponseLoading ? emptyState : undefined}
        />
    )
}

function SortingHeaderColumn({
    columnKey,
    sortOrder,
    setSortOrder,
    children,
}: {
    columnKey: SymbolSetOrder
    sortOrder: SymbolSetOrder
    setSortOrder: (sortOrder: SymbolSetOrder) => void
    children: React.ReactNode
}): JSX.Element {
    const isUsed = sortOrder.includes(columnKey)
    const order = sortOrder.startsWith('-') ? 'desc' : 'asc'
    const onSortOrderToggle = (): void => {
        if (isUsed) {
            setSortOrder((order === 'asc' ? `-${columnKey}` : columnKey) as SymbolSetOrder)
        } else {
            setSortOrder(columnKey as SymbolSetOrder)
        }
    }
    return (
        <div className="flex items-center gap-2 cursor-pointer" onClick={() => onSortOrderToggle()}>
            <div className="font-semibold">{children}</div>
            {
                match([isUsed, order])
                    .with([true, 'asc'], () => <IconArrowUp />)
                    .with([true, 'desc'], () => <IconArrowDown />)
                    .with([false, P.any], () => <IconSort />)
                    .otherwise(() => null) as JSX.Element
            }
        </div>
    )
}
