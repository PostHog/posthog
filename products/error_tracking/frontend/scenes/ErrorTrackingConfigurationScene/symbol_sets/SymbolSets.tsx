import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheckCircle, IconRevert, IconTrash, IconUpload, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDialog,
    LemonSegmentedButton,
    LemonTable,
    LemonTableColumns,
    LemonTabs,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingSymbolSet, SymbolSetStatusFilter } from 'lib/components/Errors/types'
import { JSONViewer } from 'lib/components/JSONViewer'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { UploadModal } from './UploadModal'
import { symbolSetLogic } from './symbolSetLogic'

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
    const { pagination, symbolSets, symbolSetResponseLoading } = useValues(symbolSetLogic)
    const { deleteSymbolSet, setUploadSymbolSetId } = useActions(symbolSetLogic)

    const columns: LemonTableColumns<ErrorTrackingSymbolSet> = [
        {
            title: 'Source',
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
        { title: 'Created At', dataIndex: 'created_at', render: (data) => humanFriendlyDetailedTime(data as string) },
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
            expandable={{
                noIndent: true,
                expandedRowRender: function RenderPropertiesTable(symbolSet) {
                    return <SymbolSetStackFrames symbolSet={symbolSet} />
                },
            }}
        />
    )
}

const SymbolSetStackFrames = ({ symbolSet }: { symbolSet: ErrorTrackingSymbolSet }): JSX.Element => {
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const { loadForSymbolSet } = useActions(stackFrameLogic)
    const [activeTab, setActiveTab] = useState<'contents' | 'context'>('contents')

    useEffect(() => {
        loadForSymbolSet(symbolSet.id)
    }, [loadForSymbolSet, symbolSet])

    const frames = Object.values(stackFrameRecords).filter((r) => r.symbol_set_ref == symbolSet.ref)

    return (
        <LemonCollapse
            size="small"
            panels={frames.map(({ id, raw_id, contents, context }) => ({
                key: id,
                header: raw_id,
                className: 'py-0',
                content: (
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={setActiveTab}
                        tabs={[
                            { key: 'contents', label: 'Contents', content: <JSONViewer src={contents} name={null} /> },
                            context && {
                                key: 'context',
                                label: 'Context',
                                content: <JSONViewer src={context} name={null} />,
                            },
                        ]}
                    />
                ),
            }))}
            embedded
        />
    )
}
