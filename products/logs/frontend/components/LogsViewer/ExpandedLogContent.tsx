import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconFilter, IconMinusSquare, IconPlusSquare } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { IconTableChart } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { AttributeBreakdowns } from 'products/logs/frontend/AttributeBreakdowns'
import { ParsedLogMessage } from 'products/logs/frontend/types'

import { logsViewerLogic } from './logsViewerLogic'

export interface ExpandedLogContentProps {
    log: ParsedLogMessage
    logIndex: number
}

export function ExpandedLogContent({ log, logIndex }: ExpandedLogContentProps): JSX.Element {
    const { expandedAttributeBreakdowns, tabId, cursorIndex, cursorAttributeIndex, isAttributeColumn } =
        useValues(logsViewerLogic)
    const { addFilter, toggleAttributeBreakdown, toggleAttributeColumn, recomputeRowHeights, userSetCursorAttribute } =
        useActions(logsViewerLogic)
    const containerRef = useRef<HTMLDivElement>(null)

    const isThisLogFocused = cursorIndex === logIndex

    // Scroll focused attribute into view
    useEffect(() => {
        if (isThisLogFocused && cursorAttributeIndex !== null && containerRef.current) {
            const rows = containerRef.current.querySelectorAll('tbody tr')
            const targetRow = rows[cursorAttributeIndex]
            if (targetRow) {
                targetRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
            }
        }
    }, [isThisLogFocused, cursorAttributeIndex])

    const handleToggleBreakdown = (attributeKey: string): void => {
        toggleAttributeBreakdown(log.uuid, attributeKey)
        // Trigger row height recomputation after breakdown toggle
        recomputeRowHeights([log.uuid])
    }

    const expandedBreakdownsForThisLog = expandedAttributeBreakdowns[log.uuid] || []

    const rows: { key: string; value: string; type: PropertyFilterType; index: number }[] = [
        ...Object.entries(log.resource_attributes as Record<string, string>).map(([key, value], index) => ({
            key,
            value,
            type: PropertyFilterType.LogResourceAttribute,
            index,
        })),
        ...Object.entries(log.attributes).map(([key, value], index) => ({
            key,
            value,
            type: PropertyFilterType.LogAttribute,
            index,
        })),
    ]

    return (
        <div ref={containerRef} className="bg-primary border-t border-border">
            <LemonTable
                embedded
                showHeader={false}
                size="small"
                rowKey="key"
                onRow={(record) => ({
                    onClick: () => userSetCursorAttribute(logIndex, record.index),
                    className: cn(
                        'cursor-pointer',
                        isThisLogFocused && cursorAttributeIndex === record.index && 'bg-primary-highlight'
                    ),
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
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        handleToggleBreakdown(record.key)
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
