import React from 'react'

import { IconCopy, IconMinusSquare, IconPlusSquare } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { IconTableChart } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

import { PropertyOperator } from '~/types'

export interface LogsViewerCellPopoverProps {
    attributeKey: string
    value: unknown
    isColumn?: boolean
    onAddFilter?: (key: string, value: string, operator?: PropertyOperator) => void
    onToggleColumn?: (key: string) => void
    children: React.ReactElement
}

export function LogsViewerCellPopover({
    attributeKey,
    value,
    isColumn = false,
    onAddFilter,
    onToggleColumn,
    children,
}: LogsViewerCellPopoverProps): JSX.Element {
    const displayValue = value != null ? String(value) : '-'
    const isLongValue = displayValue.length > 50

    return (
        <LemonDropdown
            placement="top"
            showArrow
            trigger="hover"
            closeOnClickInside={false}
            overlay={
                <div className="p-2 max-w-md">
                    <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="font-semibold text-xs text-muted truncate" title={attributeKey}>
                            {attributeKey}
                        </span>
                        <div className="flex items-center gap-1 shrink-0">
                            <LemonButton
                                size="xsmall"
                                icon={<IconCopy />}
                                tooltip="Copy value"
                                onClick={() => copyToClipboard(displayValue, 'attribute value')}
                            />
                            {onAddFilter && (
                                <>
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconPlusSquare />}
                                        tooltip="Add as filter"
                                        onClick={() => onAddFilter(attributeKey, displayValue)}
                                    />
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconMinusSquare />}
                                        tooltip="Exclude as filter"
                                        onClick={() => onAddFilter(attributeKey, displayValue, PropertyOperator.IsNot)}
                                    />
                                </>
                            )}
                            {onToggleColumn && (
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconTableChart />}
                                    tooltip={isColumn ? 'Remove from columns' : 'Add as column'}
                                    active={isColumn}
                                    onClick={() => onToggleColumn(attributeKey)}
                                />
                            )}
                        </div>
                    </div>
                    <div
                        className={cn(
                            'font-mono text-xs bg-bg-3000 rounded p-2',
                            isLongValue && 'max-h-48 overflow-y-auto'
                        )}
                    >
                        <span className="whitespace-pre-wrap break-all">{displayValue}</span>
                    </div>
                </div>
            }
        >
            {children}
        </LemonDropdown>
    )
}
