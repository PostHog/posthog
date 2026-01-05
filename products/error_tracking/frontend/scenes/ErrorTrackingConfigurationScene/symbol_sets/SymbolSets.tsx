import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { P, match } from 'ts-pattern'

import { IconCheckCircle, IconRevert, IconSort, IconTrash, IconUpload, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonSegmentedButton,
    LemonTable,
    LemonTableColumns,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { ErrorTrackingSymbolSet, SymbolSetStatusFilter } from 'lib/components/Errors/types'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { ReleasePreviewPill } from 'products/error_tracking/frontend/components/ReleasesPreview/ReleasePreviewPill'

import { UploadModal } from './UploadModal'
import { SymbolSetOrder, symbolSetLogic } from './symbolSetLogic'

const SYMBOL_SET_FILTER_OPTIONS = [
    {
        label: <IconCheckCircle />,
        value: 'valid',
    },
    {
        label: <IconWarning />,
        value: 'invalid',
    },
    {
        label: 'All',
        value: 'all',
    },
] as { label: string; value: SymbolSetStatusFilter }[]

export function SymbolSets(): JSX.Element {
    const { symbolSetStatusFilter } = useValues(symbolSetLogic)
    const { loadSymbolSets, setSymbolSetStatusFilter } = useActions(symbolSetLogic)

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
                <div className="flex justify-end items-center gap-2">
                    <span className="mb-0">Status:</span>
                    <LemonSegmentedButton
                        size="xsmall"
                        value={symbolSetStatusFilter}
                        options={SYMBOL_SET_FILTER_OPTIONS}
                        onChange={setSymbolSetStatusFilter}
                    />
                </div>
                <SymbolSetTable />
            </div>
            <UploadModal />
        </div>
    )
}

const SymbolSetTable = (): JSX.Element => {
    // @ts-expect-error: automagical typing does not work here for some obscure reason
    const { pagination, symbolSets, symbolSetResponseLoading, symbolSetOrder } = useValues(symbolSetLogic)
    const { deleteSymbolSet, setUploadSymbolSetId, setSymbolSetOrder } = useActions(symbolSetLogic)

    const columns: LemonTableColumns<ErrorTrackingSymbolSet> = [
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
            render: (_, { failure_reason }) => {
                return (
                    <Tooltip title={failure_reason} placement="top">
                        {failure_reason ? (
                            <span className="text-danger cursor-pointer">
                                <IconWarning /> Missing
                            </span>
                        ) : (
                            <span className="text-success">
                                <IconCheckCircle /> Uploaded
                            </span>
                        )}
                    </Tooltip>
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

            render: (_, { id, failure_reason }) => {
                return (
                    <div className="flex justify-end items-center gap-1">
                        <LemonButton
                            type={failure_reason ? 'primary' : 'tertiary'}
                            size="xsmall"
                            tooltip={failure_reason ? 'Upload symbol set' : 'Replace symbol set'}
                            icon={failure_reason ? <IconUpload /> : <IconRevert />}
                            onClick={() => setUploadSymbolSetId(id)}
                        />
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            tooltip="Delete symbol set"
                            icon={<IconTrash />}
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
            <div className="font-semibold">No symbol sets found</div>
            <div className="text-secondary">
                Learn how to upload them from the{' '}
                <Link to="https://posthog.com/docs/error-tracking/upload-source-maps">docs</Link>
            </div>
        </div>
    )

    return (
        <LemonTable
            id="symbol-sets"
            pagination={pagination}
            columns={columns}
            loading={symbolSetResponseLoading}
            dataSource={symbolSets}
            emptyState={!symbolSetResponseLoading ? emptyState : undefined}
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
