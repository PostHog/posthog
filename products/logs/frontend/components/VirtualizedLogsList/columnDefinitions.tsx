import { useActions, useValues } from 'kea'
import type { RefObject } from 'react'

import { IconArrowLeft, IconArrowRight, IconChevronRight, IconEllipsis, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonMenu, Tooltip } from '@posthog/lemon-ui'

import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { LogMessage } from '~/queries/schema/schema-general'

import {
    LOGS_COLUMN_REGISTRY,
    LogsColumnConfig,
    columnLabel,
} from 'products/logs/frontend/components/LogsViewer/config/columns'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { AttributeCell } from 'products/logs/frontend/components/VirtualizedLogsList/cells/AttributeCell'
import { MessageCell } from 'products/logs/frontend/components/VirtualizedLogsList/cells/MessageCell'
import {
    CHECKBOX_WIDTH,
    DEFAULT_ATTRIBUTE_COLUMN_WIDTH,
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

export const SEVERITY_BAR_COLORS: Record<LogMessage['severity_text'], string> = {
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

export interface ConfiguredColumnCallbacks {
    onResize?: (id: string, width: number) => void
    onRemove?: (id: string) => void
    onMove?: (id: string, direction: 'left' | 'right') => void
}

/** Presentation context shared by every configured column, resolved once per table render. */
export interface ConfiguredColumnRendering {
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime' | 'displayTimezone'>
    orderBy?: LogsOrderBy
    onChangeOrderBy?: (orderBy: LogsOrderBy) => void
    wrapBody: boolean
    prettifyJson: boolean
    flexWidthRef: RefObject<number | undefined | null>
}

/** Read a server-computed custom column value off the raw row by its canonical alias. */
function customColumnValue(log: ParsedLogMessage, alias: string | undefined): string {
    if (!alias) {
        return ''
    }
    const value = (log.originalLog as unknown as Record<string, unknown>)[alias]
    return value == null ? '' : String(value)
}

function ColumnHeaderMenu({
    config,
    callbacks,
    isFirst,
    isLast,
}: {
    config: LogsColumnConfig
    callbacks: ConfiguredColumnCallbacks
    isFirst: boolean
    isLast: boolean
}): JSX.Element | null {
    const { onRemove, onMove } = callbacks
    if (!onRemove && !onMove) {
        return null
    }
    return (
        <LemonMenu
            items={[
                onMove
                    ? {
                          label: 'Move left',
                          icon: <IconArrowLeft />,
                          disabledReason: isFirst ? 'Already at the start' : undefined,
                          onClick: () => onMove(config.id, 'left'),
                      }
                    : null,
                onMove
                    ? {
                          label: 'Move right',
                          icon: <IconArrowRight />,
                          disabledReason: isLast ? 'Already at the end' : undefined,
                          onClick: () => onMove(config.id, 'right'),
                      }
                    : null,
                onRemove
                    ? {
                          label: 'Remove column',
                          icon: <IconTrash />,
                          status: 'danger' as const,
                          onClick: () => onRemove(config.id),
                      }
                    : null,
            ]}
        >
            <LemonButton size="xsmall" noPadding icon={<IconEllipsis className="text-muted" />} className="shrink-0" />
        </LemonMenu>
    )
}

function TimestampSortButton({
    orderBy,
    onChangeOrderBy,
}: Pick<ConfiguredColumnRendering, 'orderBy' | 'onChangeOrderBy'>): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            className="h-full"
            icon={orderBy === 'latest' ? <IconArrowDown /> : <IconArrowUp />}
            tooltip={
                orderBy === 'latest'
                    ? 'Showing latest first. Click to show earliest first (reloads).'
                    : 'Showing earliest first. Click to show latest first (reloads).'
            }
            onClick={() => onChangeOrderBy?.(orderBy === 'latest' ? 'earliest' : 'latest')}
            disabled={!orderBy || !onChangeOrderBy}
        />
    )
}

/**
 * The single column factory: every configured column — built-in or custom — renders through
 * here, so all of them are reorderable, removable, and resizable. Message is the one layout
 * exception (the flex fill column, so no resizer). Type differences are confined to the cell
 * renderer (timestamp -> TZLabel, message -> MessageCell, rest -> AttributeCell, which keeps
 * the PersonDisplay / ViewRecordingButton special cases) plus timestamp's sort toggle.
 */
export function createConfiguredColumn(params: {
    config: LogsColumnConfig
    alias?: string
    callbacks: ConfiguredColumnCallbacks
    rendering: ConfiguredColumnRendering
    isFirst: boolean
    isLast: boolean
}): VirtualizedTableColumn<ParsedLogMessage> {
    const { config, alias, callbacks, rendering, isFirst, isLast } = params
    const title = columnLabel(config)

    if (config.type === 'message') {
        // Pinned to the end (see normalizeColumns) — removable, but never movable
        const messageCallbacks = { ...callbacks, onMove: undefined }
        return {
            key: `col:${config.id}`,
            title,
            sizing: { type: 'flex', minWidth: MESSAGE_MIN_WIDTH },
            render: (log) => (
                <MessageColumnCell
                    log={log}
                    wrapBody={rendering.wrapBody}
                    prettifyJson={rendering.prettifyJson}
                    flexWidthRef={rendering.flexWidthRef}
                />
            ),
            renderHeader: () => (
                <div
                    className="flex items-center justify-between px-1 gap-1"
                    style={getMessageStyle(rendering.flexWidthRef.current ?? undefined)}
                >
                    <span className="truncate" title={title}>
                        {title}
                    </span>
                    <ColumnHeaderMenu config={config} callbacks={messageCallbacks} isFirst={isFirst} isLast={isLast} />
                </div>
            ),
        }
    }

    const width = config.width ?? (config.type === 'timestamp' ? TIMESTAMP_WIDTH : DEFAULT_ATTRIBUTE_COLUMN_WIDTH)
    const totalWidth = width + RESIZER_HANDLE_WIDTH

    const semanticKey = config.type === 'custom' ? (config.name ?? config.expression ?? '') : config.type
    const renderValue =
        config.type === 'timestamp'
            ? (log: ParsedLogMessage): JSX.Element => (
                  <div className="flex items-center shrink-0" style={{ width: totalWidth }}>
                      <span className="text-xs text-muted font-mono">
                          <TZLabel time={log.timestamp} {...rendering.tzLabelFormat} timestampStyle="absolute" />
                      </span>
                  </div>
              )
            : (log: ParsedLogMessage): JSX.Element => (
                  <AttributeCell
                      attributeKey={semanticKey}
                      value={
                          config.type === 'custom'
                              ? customColumnValue(log, alias)
                              : LOGS_COLUMN_REGISTRY[config.type].getValue(log)
                      }
                      width={totalWidth}
                  />
              )

    return {
        key: `col:${config.id}`,
        title,
        sizing: { type: 'resizable', width, minWidth: MIN_ATTRIBUTE_COLUMN_WIDTH },
        render: renderValue,
        renderHeader: () => (
            <ResizableElement
                defaultWidth={totalWidth}
                minWidth={MIN_ATTRIBUTE_COLUMN_WIDTH + RESIZER_HANDLE_WIDTH}
                maxWidth={Infinity}
                onResize={(newWidth) => callbacks.onResize?.(config.id, newWidth - RESIZER_HANDLE_WIDTH)}
                className="flex items-center h-full shrink-0 group/header"
                innerClassName="h-full"
            >
                <div className="flex items-center pr-3 gap-1 h-full w-full">
                    <span className="truncate flex-1" title={title}>
                        {title}
                    </span>
                    {config.type === 'timestamp' && (
                        <TimestampSortButton orderBy={rendering.orderBy} onChangeOrderBy={rendering.onChangeOrderBy} />
                    )}
                    <ColumnHeaderMenu config={config} callbacks={callbacks} isFirst={isFirst} isLast={isLast} />
                </div>
            </ResizableElement>
        ),
    }
}
