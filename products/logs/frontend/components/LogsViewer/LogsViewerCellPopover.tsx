import React from 'react'

import { IconCopy, IconMinusSquare, IconPlusSquare } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { IconTableChart } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

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

    return (
        <LemonDropdown
            placement="top"
            showArrow
            trigger="hover"
            closeOnClickInside={false}
            overlay={
                <div className="flex items-center justify-between gap-2">
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
            }
        >
            {children}
        </LemonDropdown>
    )
}
