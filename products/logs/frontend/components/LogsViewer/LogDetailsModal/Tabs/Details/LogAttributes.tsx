import { useActions, useValues } from 'kea'

import { IconFilter, IconMinusSquare, IconPlusSquare } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { AttributeBreakdowns } from 'products/logs/frontend/AttributeBreakdowns'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'

export interface LogAttributesProps {
    attributes: Record<string, string>
    type: PropertyFilterType.LogAttribute | PropertyFilterType.LogResourceAttribute
    logUuid: string
    title: string
}

export function LogAttributes({ attributes, type, logUuid, title }: LogAttributesProps): JSX.Element {
    const { expandedAttributeBreakdowns, tabId, isAttributeColumn } = useValues(logsViewerLogic)
    const { addFilter, toggleAttributeColumn, toggleAttributeBreakdown } = useActions(logsViewerLogic)

    const expandedBreakdownsForThisLog = expandedAttributeBreakdowns[logUuid] || []

    const rows = Object.entries(attributes).map(([key, value], index) => ({
        key,
        value,
        type,
        index,
    }))

    if (rows.length === 0) {
        return <></>
    }

    return (
        <div className="bg-primary rounded border border-border overflow-hidden">
            <div className="px-3 py-2 bg-bg-light border-b border-border">
                <span className="text-xs font-semibold text-muted uppercase">{title}</span>
            </div>
            <LemonTable
                embedded
                showHeader={false}
                size="small"
                rowKey="key"
                onRow={(record) => ({
                    className: cn('cursor-pointer'),
                    onClick: () => toggleAttributeBreakdown(logUuid, record.key),
                })}
                columns={[
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, record) => (
                            <div className="flex gap-x-0">
                                <LemonButton
                                    tooltip="Add as filter"
                                    size="xsmall"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        addFilter(record.key, record.value, PropertyOperator.Exact, record.type)
                                    }}
                                >
                                    <IconPlusSquare />
                                </LemonButton>
                                <LemonButton
                                    tooltip="Exclude as filter"
                                    size="xsmall"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        addFilter(record.key, record.value, PropertyOperator.IsNot, record.type)
                                    }}
                                >
                                    <IconMinusSquare />
                                </LemonButton>
                                <LemonButton
                                    tooltip="Show breakdown"
                                    size="xsmall"
                                    active={expandedBreakdownsForThisLog.includes(record.key)}
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        toggleAttributeBreakdown(logUuid, record.key)
                                    }}
                                >
                                    <IconFilter />
                                </LemonButton>
                                <LemonButton
                                    tooltip={isAttributeColumn(record.key) ? 'Remove from columns' : 'Add as column'}
                                    size="xsmall"
                                    active={isAttributeColumn(record.key)}
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        toggleAttributeColumn(record.key)
                                    }}
                                    className={isAttributeColumn(record.key) ? '' : 'opacity-30'}
                                >
                                    <IconTableChart />
                                </LemonButton>
                            </div>
                        ),
                    },
                    {
                        title: 'Key',
                        key: 'key',
                        dataIndex: 'key',
                        width: 0,
                        render: (_, record) => (
                            <span className="font-mono text-xs text-muted whitespace-nowrap">{record.key}</span>
                        ),
                    },
                    {
                        title: 'Value',
                        key: 'value',
                        dataIndex: 'value',
                        render: (_, record) => (
                            <CopyToClipboardInline
                                explicitValue={record.value}
                                description="attribute value"
                                iconSize="xsmall"
                                iconPosition="start"
                                selectable
                                className="gap-1 font-mono text-xs"
                            >
                                {record.value}
                            </CopyToClipboardInline>
                        ),
                    },
                ]}
                dataSource={rows}
                expandable={{
                    noIndent: true,
                    showRowExpansionToggle: false,
                    isRowExpanded: (record) => expandedBreakdownsForThisLog.includes(record.key),
                    expandedRowRender: (record) => (
                        <AttributeBreakdowns
                            attribute={record.key}
                            addFilter={addFilter}
                            tabId={tabId}
                            type={record.type}
                        />
                    ),
                }}
            />
        </div>
    )
}
