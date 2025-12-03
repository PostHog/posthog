import { IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'

import { LogMessage } from '~/queries/schema/schema-general'

import { LogsTableRowActions } from 'products/logs/frontend/components/LogsTable/LogsTableRowActions'
import { ParsedLogMessage } from 'products/logs/frontend/types'

const SEVERITY_BAR_COLORS: Record<LogMessage['severity_text'], string> = {
    trace: 'bg-muted-alt',
    debug: 'bg-muted',
    info: 'bg-brand-blue',
    warn: 'bg-warning',
    error: 'bg-danger',
    fatal: 'bg-danger-dark',
}

export interface LogRowProps {
    log: ParsedLogMessage
    isHighlighted: boolean
    pinned: boolean
    showPinnedWithOpacity: boolean
    wrapBody: boolean
    prettifyJson: boolean
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime'>
    onTogglePin: (uuid: string) => void
    onSetHighlighted: (uuid: string | null) => void
}

export function LogRow({
    log,
    isHighlighted,
    pinned,
    showPinnedWithOpacity,
    wrapBody,
    prettifyJson,
    tzLabelFormat,
    onTogglePin,
    onSetHighlighted,
}: LogRowProps): JSX.Element {
    const isNew = 'new' in log && log.new

    return (
        <div
            key={isNew ? `new-${log.uuid}` : log.uuid}
            className={cn(
                'flex items-center gap-3 border-b border-border cursor-pointer hover:bg-fill-highlight-100 group',
                isHighlighted && 'bg-primary-highlight',
                pinned && 'bg-warning-highlight',
                pinned && showPinnedWithOpacity && 'opacity-50',
                isNew && 'VirtualizedLogsList__row--new'
            )}
            onClick={() => onSetHighlighted(isHighlighted ? null : log.uuid)}
        >
            <Tooltip title={log.severity_text.toUpperCase()}>
                <div
                    className={cn(
                        'w-1 self-stretch rounded-full shrink-0',
                        SEVERITY_BAR_COLORS[log.severity_text] ?? 'bg-muted-3000'
                    )}
                />
            </Tooltip>
            <span className="w-[180px] text-xs text-muted shrink-0 font-mono">
                <TZLabel time={log.timestamp} {...tzLabelFormat} showNow={false} showToday={false} />
            </span>
            <span
                className={cn(
                    'flex-1 font-mono text-xs break-all py-1.5',
                    wrapBody || (prettifyJson && log.parsedBody) ? 'whitespace-pre-wrap' : 'truncate'
                )}
            >
                {log.parsedBody && prettifyJson ? JSON.stringify(log.parsedBody, null, 2) : log.cleanBody}
            </span>
            <div className="flex items-center gap-1 shrink-0">
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={pinned ? <IconPinFilled /> : <IconPin />}
                    onClick={(e) => {
                        e.stopPropagation()
                        onTogglePin(log.uuid)
                    }}
                    tooltip={pinned ? 'Unpin log' : 'Pin log'}
                    className={cn(pinned ? 'text-warning' : 'text-muted opacity-0 group-hover:opacity-100')}
                />
                <div className="opacity-0 group-hover:opacity-100" onClick={(e) => e.stopPropagation()}>
                    <LogsTableRowActions log={log} />
                </div>
            </div>
        </div>
    )
}
