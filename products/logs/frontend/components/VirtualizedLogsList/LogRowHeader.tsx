import { IconArrowLeft, IconArrowRight, IconEllipsis, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonMenu } from '@posthog/lemon-ui'

import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'

import {
    ACTIONS_WIDTH,
    CHECKBOX_WIDTH,
    EXPAND_WIDTH,
    MIN_ATTRIBUTE_COLUMN_WIDTH,
    RESIZER_HANDLE_WIDTH,
    ROW_GAP,
    SEVERITY_WIDTH,
    TIMESTAMP_WIDTH,
    getAttributeColumnWidth,
    getFixedColumnsWidth,
    getMessageStyle,
} from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'

export interface LogRowHeaderProps {
    rowWidth: number
    attributeColumns?: string[]
    attributeColumnWidths?: Record<string, number>
    onRemoveAttributeColumn?: (attributeKey: string) => void
    onResizeAttributeColumn?: (attributeKey: string, width: number) => void
    onMoveAttributeColumn?: (attributeKey: string, direction: 'left' | 'right') => void
    // Selection
    selectedCount?: number
    totalCount?: number
    onSelectAll?: () => void
    onClearSelection?: () => void
}

export function LogRowHeader({
    rowWidth,
    attributeColumns = [],
    attributeColumnWidths = {},
    onRemoveAttributeColumn,
    onResizeAttributeColumn,
    onMoveAttributeColumn,
    selectedCount = 0,
    totalCount = 0,
    onSelectAll,
    onClearSelection,
}: LogRowHeaderProps): JSX.Element {
    const flexWidth =
        rowWidth -
        getFixedColumnsWidth(attributeColumns, attributeColumnWidths) -
        attributeColumns.length * RESIZER_HANDLE_WIDTH

    const allSelected = totalCount > 0 && selectedCount === totalCount
    const someSelected = selectedCount > 0 && selectedCount < totalCount

    return (
        <div
            style={{ width: rowWidth, gap: ROW_GAP }}
            className="flex items-center h-8 border-b border-border bg-bg-3000 text-xs font-semibold text-muted sticky top-0 z-10"
        >
            {/* Severity + Checkbox + Expand header space */}
            <div className="flex items-center self-stretch">
                <div style={{ width: SEVERITY_WIDTH, flexShrink: 0 }} />
                <div className="flex items-center justify-center shrink-0" style={{ width: CHECKBOX_WIDTH }}>
                    <LemonCheckbox
                        checked={someSelected ? 'indeterminate' : allSelected}
                        onChange={() => (allSelected ? onClearSelection?.() : onSelectAll?.())}
                        size="small"
                    />
                </div>
                <div style={{ width: EXPAND_WIDTH, flexShrink: 0 }} />
            </div>

            {/* Timestamp */}
            <div className="flex items-center pr-3" style={{ width: TIMESTAMP_WIDTH, flexShrink: 0 }}>
                Timestamp
            </div>

            {/* Attribute columns */}
            {attributeColumns.map((attributeKey, index) => {
                const width = getAttributeColumnWidth(attributeKey, attributeColumnWidths)
                const isFirst = index === 0
                const isLast = index === attributeColumns.length - 1
                return (
                    <ResizableElement
                        key={`attr-${attributeKey}`}
                        defaultWidth={width + RESIZER_HANDLE_WIDTH}
                        minWidth={MIN_ATTRIBUTE_COLUMN_WIDTH + RESIZER_HANDLE_WIDTH}
                        maxWidth={Infinity}
                        onResize={(newWidth) =>
                            onResizeAttributeColumn?.(attributeKey, newWidth - RESIZER_HANDLE_WIDTH)
                        }
                        className="flex items-center h-full shrink-0 group/header"
                        innerClassName="h-full"
                    >
                        <div className="flex items-center pr-3 gap-1 h-full w-full">
                            <span className="truncate flex-1" title={attributeKey}>
                                {attributeKey}
                            </span>
                            {(onRemoveAttributeColumn || onMoveAttributeColumn) && (
                                <LemonMenu
                                    items={[
                                        onMoveAttributeColumn
                                            ? {
                                                  label: 'Move left',
                                                  icon: <IconArrowLeft />,
                                                  disabledReason: isFirst ? 'Already at the start' : undefined,
                                                  onClick: () => onMoveAttributeColumn(attributeKey, 'left'),
                                              }
                                            : null,
                                        onMoveAttributeColumn
                                            ? {
                                                  label: 'Move right',
                                                  icon: <IconArrowRight />,
                                                  disabledReason: isLast ? 'Already at the end' : undefined,
                                                  onClick: () => onMoveAttributeColumn(attributeKey, 'right'),
                                              }
                                            : null,
                                        onRemoveAttributeColumn
                                            ? {
                                                  label: 'Remove column',
                                                  icon: <IconTrash />,
                                                  status: 'danger',
                                                  onClick: () => onRemoveAttributeColumn(attributeKey),
                                              }
                                            : null,
                                    ]}
                                >
                                    <LemonButton
                                        size="xsmall"
                                        noPadding
                                        icon={<IconEllipsis className="text-muted" />}
                                        className="opacity-0 group-hover/header:opacity-100 shrink-0"
                                    />
                                </LemonMenu>
                            )}
                        </div>
                    </ResizableElement>
                )
            })}

            {/* Message */}
            <div className="flex items-center px-1" style={getMessageStyle(flexWidth)}>
                Message
            </div>

            {/* Actions (no label) */}
            <div className="flex items-center px-1" style={{ width: ACTIONS_WIDTH, flexShrink: 0 }} />
        </div>
    )
}
