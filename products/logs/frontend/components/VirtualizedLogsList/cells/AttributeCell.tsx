import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { Link } from '@posthog/lemon-ui'

import ViewRecordingButton, {
    RecordingPlayerType,
    ViewRecordingButtonVariant,
} from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LogsViewerCellPopover } from 'products/logs/frontend/components/LogsViewer/LogsViewerCellPopover'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { LogRowScrollButtons } from 'products/logs/frontend/components/VirtualizedLogsList/LogRowScrollButtons'
import { useCellScroll } from 'products/logs/frontend/components/VirtualizedLogsList/useCellScroll'
import { logsConfigLogic } from 'products/logs/frontend/logsConfigLogic'
import { isDistinctIdKey, isSessionIdKey } from 'products/logs/frontend/utils'
import { traceUrl } from 'products/tracing/frontend/traceLinks'

export interface AttributeCellProps {
    attributeKey: string
    value: string
    width: number
    /** The row's timestamp; lets the trace_id cell link with a time hint for the cold-load query. */
    timestamp?: string
}

export const AttributeCell = memo(function AttributeCell({
    attributeKey,
    value,
    width,
    timestamp,
}: AttributeCellProps): JSX.Element {
    const { id, isAttributeColumn } = useValues(logsViewerLogic)
    const { configuredSessionIdKeys } = useValues(logsConfigLogic)
    const { addFilter, toggleAttributeColumn } = useActions(logsViewerLogic)
    const tracingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Tracing,
        AccessControlLevel.Viewer
    )

    const { scrollRef, handleScroll, startScrolling, stopScrolling } = useCellScroll({
        id,
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
                    ) : isSessionIdKey(attributeKey, configuredSessionIdKeys) && value ? (
                        <ViewRecordingButton
                            sessionId={value}
                            openPlayerIn={RecordingPlayerType.Modal}
                            label={value}
                            variant={ViewRecordingButtonVariant.Link}
                            className="font-mono text-xs whitespace-nowrap pr-24"
                            checkRecordingExists
                        />
                    ) : attributeKey === 'trace_id' && value && !tracingDisabledReason ? (
                        <Link
                            to={traceUrl({ traceId: value, ts: timestamp ?? null })}
                            className="font-mono text-xs whitespace-nowrap pr-24"
                            title={value}
                        >
                            {/* Link doesn't take data-attr; the span gives autocapture a named element. */}
                            <span data-attr="logs-viewer-trace-link">{value}</span>
                        </Link>
                    ) : (
                        <span className="font-mono text-xs text-muted whitespace-nowrap pr-24" title={value}>
                            {value || '-'}
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
