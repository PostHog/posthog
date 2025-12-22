import { useActions, useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { JsonType } from '~/types'

import { LogsViewerCellPopover } from 'products/logs/frontend/components/LogsViewer/LogsViewerCellPopover'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'
import { LogRowScrollButtons } from 'products/logs/frontend/components/VirtualizedLogsList/LogRowScrollButtons'
import { useCellScroll } from 'products/logs/frontend/components/VirtualizedLogsList/useCellScroll'

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

    const { scrollRef, handleScroll, startScrolling, stopScrolling } = useCellScroll({
        tabId,
        cellKey: 'message',
        enabled: !wrapBody,
    })

    const displayValue = prettifyJson && parsedBody ? JSON.stringify(parsedBody, null, 2) : message

    return (
        <LogsViewerCellPopover attributeKey="body" value={displayValue} onAddFilter={addFilter}>
            <div style={style} className="relative flex items-start self-stretch group/msg">
                <div
                    ref={wrapBody ? undefined : scrollRef}
                    onScroll={wrapBody ? undefined : handleScroll}
                    className={cn(
                        'flex-1 self-stretch',
                        wrapBody ? 'overflow-hidden' : 'overflow-x-auto hide-scrollbar'
                    )}
                >
                    <div className={cn('flex items-center', wrapBody ? 'py-1.5' : 'w-max min-h-full')}>
                        {prettifyJson && parsedBody ? (
                            <pre
                                className={cn(
                                    'font-mono text-xs inline-block mb-0',
                                    wrapBody ? 'whitespace-pre-wrap break-all' : 'whitespace-nowrap pr-16'
                                )}
                            >
                                {displayValue}
                            </pre>
                        ) : (
                            <span
                                className={cn(
                                    'font-mono text-xs',
                                    wrapBody ? 'whitespace-pre-wrap break-all' : 'whitespace-nowrap pr-16'
                                )}
                            >
                                {displayValue}
                            </span>
                        )}
                    </div>
                </div>
                {!wrapBody && (
                    <LogRowScrollButtons
                        onStartScrolling={startScrolling}
                        onStopScrolling={stopScrolling}
                        className="group-hover/msg:opacity-100"
                    />
                )}
            </div>
        </LogsViewerCellPopover>
    )
}
