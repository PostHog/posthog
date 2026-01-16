import { useActions, useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { JsonType } from '~/types'

import { LogsViewerCellPopover } from 'products/logs/frontend/components/LogsViewer/LogsViewerCellPopover'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { LOG_ROW_FAB_WIDTH } from 'products/logs/frontend/components/VirtualizedLogsList/layoutUtils'
import { useCellScrollRef } from 'products/logs/frontend/components/VirtualizedLogsList/useCellScroll'

export interface MessageCellProps {
    message: string
    wrapBody: boolean
    prettifyJson: boolean
    parsedBody: JsonType | null
    style?: React.CSSProperties
}

export function MessageCell({ message, wrapBody, prettifyJson, parsedBody, style }: MessageCellProps): JSX.Element {
    const { tabId } = useValues(logsViewerLogic)
    const { addFilter } = useActions(logsViewerLogic)
    const { scrollRef, handleScroll } = useCellScrollRef({ tabId, cellKey: 'message', enabled: !wrapBody })

    const displayValue = prettifyJson && parsedBody ? JSON.stringify(parsedBody, null, 2) : message

    return (
        <LogsViewerCellPopover attributeKey="body" value={displayValue} onAddFilter={addFilter}>
            <div style={style} className="relative flex items-start self-stretch">
                <div
                    ref={wrapBody ? undefined : scrollRef}
                    onScroll={wrapBody ? undefined : handleScroll}
                    className={cn(
                        'flex-1 self-stretch',
                        wrapBody ? 'overflow-hidden' : 'overflow-x-auto hide-scrollbar'
                    )}
                >
                    <div className={cn('flex items-center min-h-full', wrapBody ? 'py-1.5' : 'w-max')}>
                        {prettifyJson && parsedBody ? (
                            <pre
                                className={cn(
                                    'font-mono text-xs inline-block mb-0',
                                    wrapBody ? 'whitespace-pre-wrap break-all' : 'whitespace-nowrap'
                                )}
                                style={{ paddingRight: wrapBody ? 16 : LOG_ROW_FAB_WIDTH }}
                            >
                                {displayValue}
                            </pre>
                        ) : (
                            <span
                                className={cn(
                                    'font-mono text-xs',
                                    wrapBody ? 'whitespace-pre-wrap break-all' : 'whitespace-nowrap'
                                )}
                                style={{ paddingRight: wrapBody ? 16 : LOG_ROW_FAB_WIDTH }}
                            >
                                {displayValue}
                            </span>
                        )}
                    </div>
                </div>
            </div>
        </LogsViewerCellPopover>
    )
}
