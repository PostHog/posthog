import { IconPinFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel, TZLabelProps } from 'lib/components/TZLabel'

import { ParsedLogMessage } from 'products/logs/frontend/types'

interface MobileLogRowProps {
    log: ParsedLogMessage
    tzLabelFormat: Pick<TZLabelProps, 'formatDate' | 'formatTime' | 'displayTimezone'>
    pinned: boolean
    onTogglePin: (log: ParsedLogMessage) => void
    onClick: () => void
}

export function MobileLogRow({ log, tzLabelFormat, pinned, onTogglePin, onClick }: MobileLogRowProps): JSX.Element {
    return (
        <LemonButton
            fullWidth
            onClick={onClick}
            className="border-b rounded-none py-2 ph-no-capture"
            data-attr="logs-mobile-row"
            sideAction={
                pinned
                    ? {
                          icon: <IconPinFilled />,
                          onClick: () => onTogglePin(log),
                          tooltip: 'Unpin log',
                          'aria-label': 'Unpin log',
                          'data-attr': 'logs-mobile-row-unpin',
                      }
                    : undefined
            }
        >
            <span className="flex flex-col gap-1 min-w-0 w-full font-normal">
                <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted">
                    <span className="uppercase font-semibold">{log.severity_text}</span>
                    <TZLabel time={log.timestamp} {...tzLabelFormat} timestampStyle="absolute" showPopover={false} />
                </span>
                {log.resource_attributes?.['service.name'] && (
                    <span className="text-xs text-muted truncate">
                        {String(log.resource_attributes['service.name'])}
                    </span>
                )}
                <span className="font-mono text-xs break-all line-clamp-2">{log.cleanBody || log.body}</span>
            </span>
        </LemonButton>
    )
}
