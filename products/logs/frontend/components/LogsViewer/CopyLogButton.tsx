import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ParsedLogMessage } from 'products/logs/frontend/types'

function copyLogRaw(log: ParsedLogMessage): void {
    void copyToClipboard(JSON.stringify(log.originalLog, null, 2), 'raw log')
}

function copyLogMessage(log: ParsedLogMessage): void {
    void copyToClipboard(log.body, 'log message')
}

interface CopyLogButtonProps {
    log: ParsedLogMessage
    size?: 'xsmall' | 'small'
    noPadding?: boolean
    className?: string
}

/** Icon button that opens a two-choice menu: copy the log message, or copy the full raw log. */
export function CopyLogButton({ log, size = 'xsmall', noPadding, className }: CopyLogButtonProps): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <LemonButton
                        size={size}
                        noPadding={noPadding}
                        icon={<IconCopy />}
                        tooltip="Copy log"
                        aria-label="Copy log"
                        className={className}
                        data-attr="logs-viewer-copy-message"
                    />
                }
            />
            <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => copyLogMessage(log)} data-attr="logs-viewer-copy-message-body">
                    <IconCopy />
                    Copy message
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => copyLogRaw(log)} data-attr="logs-viewer-copy-message-raw">
                    <IconCopy />
                    Copy raw
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
