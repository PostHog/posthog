import { useActions, useValues } from 'kea'
import type { RefObject } from 'react'

import { IconArrowLeft, IconArrowRight, IconChevronRight, IconEllipsis, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonMenu, Tooltip } from '@posthog/lemon-ui'

import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { LogMessage } from '~/queries/schema/schema-general'

import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { AttributeCell } from 'products/logs/frontend/components/VirtualizedLogsList/cells/AttributeCell'
import { MessageCell } from 'products/logs/frontend/components/VirtualizedLogsList/cells/MessageCell'
import {
    CHECKBOX_WIDTH,
    EXPAND_WIDTH,
    MESSAGE_MIN_WIDTH,
    MIN_ATTRIBUTE_COLUMN_WIDTH,
    RESIZER_HANDLE_WIDTH,
    SEVERITY_WIDTH,
    TIMESTAMP_WIDTH,
    getMessageStyle,
} from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { VirtualizedTableColumn } from 'products/logs/frontend/components/VirtualizedLogsList/types'
import { LogsOrderBy, ParsedLogMessage } from 'products/logs/frontend/types'

const SEVERITY_BAR_COLORS: Record<LogMessage['severity_text'], string> = {
    trace: 'bg-muted-alt',
    debug: 'bg-muted',
    info: 'bg-brand-blue',
    warn: 'bg-warning',
    error: 'bg-danger',
    fatal: 'bg-danger-dark',
}

// Cell components that read per-row state from kea — avoids baking
// frequently-changing state into column closures.

function ControlsCell({ log }: { log: ParsedLogMessage }): JSX.Element {
    const { selectedLogIds, expandedLogIds } = useValues(logsViewerLogic)
    const { toggleSelectLog, toggleExpandLog } = useActions(logsViewerLogic)

    const severityColor = SEVERITY_BAR_COLORS[log.severity_text] ?? 'bg-muted-3000'
    const isSelected = !!selectedLogIds[log.uuid]
    const isExpanded = !!expandedLogIds[log.uuid]

    return (
        <div className="flex items-center self-stretch">
            <Tooltip title={log.severity_text.toUpperCase()}>
                <div className="flex items-stretch self-stretch" style={{ width: SEVERITY_WIDTH, flexShrink: 0 }}>
                    <div className={cn('w-1 rounded-full', severityColor)} />
                </div>
            </Tooltip>
            <div className="flex items-center justify-center shrink-0" style={{ width: CHECKBOX_WIDTH }}>
                <LemonCheckbox
                    checked={isSelected}
                    onChange={() => toggleSelectLog(log.uuid)}
                    stopPropagation
                    size="small"
                />
            </div>
            <div
                className="flex items-stretch self-stretch justify-center"
                style={{ width: EXPAND_WIDTH, flexShrink: 0 }}
            >
                <LemonButton
                    size="xsmall"
                    icon={<IconChevronRight className={cn('transition-transform', isExpanded && 'rotate-90')} />}
                    onMouseDown={(e) => {
                        e.stopPropagation()
                        toggleExpandLog(log.uuid)
                    }}
                    onClick={(e) => e.stopPropagation()}
                />
            </div>
        </div>
    )
}

function ControlsHeader({ dataSourceRef }: { dataSourceRef: RefObject<ParsedLogMessage[]> }): JSX.Element {
    const { selectedCount } = useValues(logsViewerLogic)
    const { selectAll, clearSelection } = useActions(logsViewerLogic)

    const totalCount = dataSourceRef.current?.length ?? 0
    const allSelected = totalCount > 0 && selectedCount === totalCount
    const someSelected = selectedCount > 0 && selectedCount < totalCount

    return (
        <div className="flex items-center self-stretch">
            <div style={{ width: SEVERITY_WIDTH, flexShrink: 0 }} />
            <div className="flex items-center justify-center shrink-0" style={{ width: CHECKBOX_WIDTH }}>
                <LemonCheckbox
                    checked={someSelected ? 'indeterminate' : allSelected}
                    onChange={() => (allSelected ? clearSelection() : selectAll(dataSourceRef.current ?? undefined))}
                    size="small"
                />
            </div>
            <div style={{ width: EXPAND_WIDTH, flexShrink: 0 }} />
        </div>
    )
}

function MessageColumnCell({
    log,
    wrapBody,
    prettifyJson,
    flexWidthRef,
}: {
    log: ParsedLogMessage
    wrapBody: boolean
    prettifyJson: boolean
    flexWidthRef: RefObject<number | undefined | null>
}): JSX.Element {
    const { prettifiedLogIds } = useValues(logsViewerLogic)
    const isPrettified = prettifiedLogIds.has(log.uuid)

    return (
        <MessageCell
            message={log.cleanBody}
            wrapBody={isPrettified || wrapBody}
            prettifyJson={isPrettified || prettifyJson}
            parsedBody={log.parsedBody}
            style={getMessageStyle(flexWidthRef.current ?? undefined)}
        />
    )
}

// Column factory functions — only structural/settings params, no per-row state.

export function createControlsColumn(params: {
    dataSourceRef: RefObject<ParsedLogMessage[]>
}): VirtualizedTableColumn<ParsedLogMessage> {
    return {
        key: 'controls',
        sizing: { type: 'fixed', width: SEVERITY_WIDTH + CHECKBOX_WIDTH + EXPAND_WIDTH },
        render: (log) => <ControlsCell log={log} />,
        renderHeader: () => <ControlsHeader dataSourceRef={params.dataSourceRef} />,
    }
}

export function createTimestampColumn(params: {
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime' | 'displayTimezone'>
    orderBy?: LogsOrderBy
    onChangeOrderBy?: (orderBy: LogsOrderBy) => void
}): VirtualizedTableColumn<ParsedLogMessage> {
    const { tzLabelFormat, orderBy, onChangeOrderBy } = params

    return {
        key: 'timestamp',
        title: 'Timestamp',
        sizing: { type: 'fixed', width: TIMESTAMP_WIDTH },
        render: (log) => (
            <div className="flex items-center shrink-0" style={{ width: TIMESTAMP_WIDTH }}>
                <span className="text-xs text-muted font-mono">
                    <TZLabel time={log.timestamp} {...tzLabelFormat} timestampStyle="absolute" />
                </span>
            </div>
        ),
        renderHeader: () => (
            <div
                className="flex items-center justify-between pr-3 gap-1 h-full border-r"
                style={{ width: TIMESTAMP_WIDTH, flexShrink: 0 }}
            >
                Timestamp
                <LemonButton
                    size="xsmall"
                    className="h-full"
                    icon={orderBy === 'latest' ? <IconArrowDown /> : <IconArrowUp />}
                    tooltip={
                        orderBy === 'latest'
                            ? 'Showing latest first. Click to show earliest first (reloads).'
                            : 'Showing earliest first. Click to show latest first (reloads).'
                    }
                    onClick={() => {
                        const newOrderBy = orderBy === 'latest' ? 'earliest' : 'latest'
                        onChangeOrderBy?.(newOrderBy)
                    }}
                    disabled={!orderBy || !onChangeOrderBy}
                />
            </div>
        ),
    }
}

export function createAttributeColumn(params: {
    attributeKey: string
    width: number
    onResize?: (attributeKey: string, width: number) => void
    onRemove?: (attributeKey: string) => void
    onMove?: (attributeKey: string, direction: 'left' | 'right') => void
    isFirst: boolean
    isLast: boolean
}): VirtualizedTableColumn<ParsedLogMessage> {
    const { attributeKey, width, onResize, onRemove, onMove, isFirst, isLast } = params
    const totalWidth = width + RESIZER_HANDLE_WIDTH

    return {
        key: `attr:${attributeKey}`,
        title: attributeKey,
        sizing: { type: 'resizable', width, minWidth: MIN_ATTRIBUTE_COLUMN_WIDTH },
        render: (log) => {
            const attrValue = log.attributes[attributeKey] ?? log.resource_attributes[attributeKey]
            return (
                <AttributeCell
                    attributeKey={attributeKey}
                    value={attrValue != null ? String(attrValue) : ''}
                    width={totalWidth}
                />
            )
        },
        renderHeader: () => (
            <ResizableElement
                defaultWidth={totalWidth}
                minWidth={MIN_ATTRIBUTE_COLUMN_WIDTH + RESIZER_HANDLE_WIDTH}
                maxWidth={Infinity}
                onResize={(newWidth) => onResize?.(attributeKey, newWidth - RESIZER_HANDLE_WIDTH)}
                className="flex items-center h-full shrink-0 group/header"
                innerClassName="h-full"
            >
                <div className="flex items-center pr-3 gap-1 h-full w-full">
                    <span className="truncate flex-1" title={attributeKey}>
                        {attributeKey}
                    </span>
                    {(onRemove || onMove) && (
                        <LemonMenu
                            items={[
                                onMove
                                    ? {
                                          label: 'Move left',
                                          icon: <IconArrowLeft />,
                                          disabledReason: isFirst ? 'Already at the start' : undefined,
                                          onClick: () => onMove(attributeKey, 'left'),
                                      }
                                    : null,
                                onMove
                                    ? {
                                          label: 'Move right',
                                          icon: <IconArrowRight />,
                                          disabledReason: isLast ? 'Already at the end' : undefined,
                                          onClick: () => onMove(attributeKey, 'right'),
                                      }
                                    : null,
                                onRemove
                                    ? {
                                          label: 'Remove column',
                                          icon: <IconTrash />,
                                          status: 'danger' as const,
                                          onClick: () => onRemove(attributeKey),
                                      }
                                    : null,
                            ]}
                        >
                            <LemonButton
                                size="xsmall"
                                noPadding
                                icon={<IconEllipsis className="text-muted" />}
                                className="shrink-0"
                            />
                        </LemonMenu>
                    )}
                </div>
            </ResizableElement>
        ),
    }
}

export function createMessageColumn(params: {
    wrapBody: boolean
    prettifyJson: boolean
    flexWidthRef: RefObject<number | undefined | null>
}): VirtualizedTableColumn<ParsedLogMessage> {
    const { wrapBody, prettifyJson, flexWidthRef } = params

    return {
        key: 'message',
        title: 'Message',
        sizing: { type: 'flex', minWidth: MESSAGE_MIN_WIDTH },
        render: (log) => (
            <MessageColumnCell log={log} wrapBody={wrapBody} prettifyJson={prettifyJson} flexWidthRef={flexWidthRef} />
        ),
        renderHeader: () => (
            <div className="flex items-center px-1" style={getMessageStyle(flexWidthRef.current ?? undefined)}>
                Message
            </div>
        ),
    }
}
