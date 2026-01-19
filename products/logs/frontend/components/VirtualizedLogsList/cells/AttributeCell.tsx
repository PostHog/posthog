import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { LogsViewerCellPopover } from 'products/logs/frontend/components/LogsViewer/LogsViewerCellPopover'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { LogRowScrollButtons } from 'products/logs/frontend/components/VirtualizedLogsList/LogRowScrollButtons'
import { useCellScroll } from 'products/logs/frontend/components/VirtualizedLogsList/useCellScroll'
import { isDistinctIdKey } from 'products/logs/frontend/utils'

export interface AttributeCellProps {
    attributeKey: string
    value: string
    width: number
}

export const AttributeCell = memo(function AttributeCell({
    attributeKey,
    value,
    width,
}: AttributeCellProps): JSX.Element {
    const { tabId, isAttributeColumn } = useValues(logsViewerLogic)
    const { addFilter, toggleAttributeColumn } = useActions(logsViewerLogic)

    const { scrollRef, handleScroll, startScrolling, stopScrolling } = useCellScroll({
        tabId,
        cellKey: `attr:${attributeKey}`,
    })

    return (
        <LogsViewerCellPopover
            attributeKey={attributeKey}
            value={value}
            isColumn={isAttributeColumn(attributeKey)}
            onAddFilter={addFilter}
            onToggleColumn={toggleAttributeColumn}
        >
            <div style={{ width, flexShrink: 0 }} className="relative flex items-center self-stretch group/attr pr-1">
                <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-x-auto hide-scrollbar">
                    {isDistinctIdKey(attributeKey) ? (
                        <span className="font-mono text-xs whitespace-nowrap pr-24" title={value}>
                            <PersonDisplay person={{ distinct_id: value }} noEllipsis inline />
                        </span>
                    ) : (
                        <span className="font-mono text-xs text-muted whitespace-nowrap pr-24" title={value}>
                            {value}
                        </span>
                    )}
                </div>
                <LogRowScrollButtons
                    onStartScrolling={startScrolling}
                    onStopScrolling={stopScrolling}
                    className="group-hover/attr:opacity-100"
                />
            </div>
        </LogsViewerCellPopover>
    )
})
