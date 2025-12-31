import { useActions, useValues } from 'kea'

import {
    IconBrackets,
    IconChevronLeft,
    IconChevronRight,
    IconCopy,
    IconExpand45,
    IconPin,
    IconPinFilled,
} from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

import { logDetailsModalLogic } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { useCellScrollControls } from 'products/logs/frontend/components/VirtualizedLogsList/useCellScroll'
import { ParsedLogMessage } from 'products/logs/frontend/types'

import { FABGroup } from './FABGroup'

export interface LogRowFABProps {
    log: ParsedLogMessage
    pinned: boolean
    isPrettified: boolean
    onTogglePin: (log: ParsedLogMessage) => void
    onTogglePrettify?: (log: ParsedLogMessage) => void
    showScrollButtons?: boolean
}

export function LogRowFAB({
    log,
    pinned,
    isPrettified,
    onTogglePin,
    onTogglePrettify,
    showScrollButtons = false,
}: LogRowFABProps): JSX.Element {
    const { tabId } = useValues(logsViewerLogic)
    const { copyLinkToLog } = useActions(logsViewerLogic)
    const { openLogDetails } = useActions(logDetailsModalLogic)
    const { startScrolling, stopScrolling } = useCellScrollControls({ tabId, cellKey: 'message' })

    return (
        <div
            className={cn(
                'absolute right-2 top-1/2 -translate-y-1/2',
                'flex items-center gap-1',
                'opacity-0 group-hover:opacity-100 transition-opacity'
            )}
            onMouseDown={(e) => e.stopPropagation()}
        >
            <FABGroup>
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={<IconExpand45 />}
                    onClick={(e) => {
                        e.preventDefault()
                        openLogDetails(log)
                    }}
                    tooltip="View log details"
                    className="text-muted"
                    data-attr="logs-viewer-view-details"
                />
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={<IconBrackets />}
                    onClick={(e) => {
                        e.preventDefault()
                        onTogglePrettify?.(log)
                    }}
                    tooltip={isPrettified ? 'Collapse JSON' : 'Prettify JSON'}
                    aria-label={isPrettified ? 'Collapse JSON' : 'Prettify JSON'}
                    className={cn(isPrettified ? 'text-brand-blue' : 'text-muted')}
                />
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={pinned ? <IconPinFilled /> : <IconPin />}
                    onClick={(e) => {
                        e.preventDefault()
                        onTogglePin(log)
                    }}
                    tooltip={pinned ? 'Unpin log' : 'Pin log'}
                    aria-label={pinned ? 'Unpin log' : 'Pin log'}
                    className={cn(pinned ? 'text-warning' : 'text-muted')}
                />
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={<IconCopy />}
                    onClick={(e) => {
                        e.preventDefault()
                        void copyToClipboard(log.body, 'log message')
                    }}
                    tooltip="Copy log message"
                    aria-label="Copy log message"
                    className="text-muted"
                    data-attr="logs-viewer-copy-message"
                />
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={<IconLink />}
                    onClick={(e) => {
                        e.preventDefault()
                        copyLinkToLog(log.uuid)
                    }}
                    tooltip="Copy link to log"
                    aria-label="Copy link to log"
                    className="text-muted"
                    data-attr="logs-viewer-copy-link"
                />
            </FABGroup>

            {showScrollButtons && (
                <FABGroup>
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconChevronLeft />}
                        aria-label="Scroll left"
                        onMouseDown={(e) => {
                            e.preventDefault()
                            startScrolling('left')
                        }}
                        onMouseUp={stopScrolling}
                        onMouseLeave={stopScrolling}
                        className="text-muted"
                    />
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconChevronRight />}
                        aria-label="Scroll right"
                        onMouseDown={(e) => {
                            e.preventDefault()
                            startScrolling('right')
                        }}
                        onMouseUp={stopScrolling}
                        onMouseLeave={stopScrolling}
                        className="text-muted"
                    />
                </FABGroup>
            )}
        </div>
    )
}
