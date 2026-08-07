import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ParsedLogMessage } from 'products/logs/frontend/types'

export function copyLogRaw(log: ParsedLogMessage): void {
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
            <DropdownMenuTrigger asChild>
                <LemonButton
                    size={size}
                    noPadding={noPadding}
                    icon={<IconCopy />}
                    tooltip="Copy log"
                    aria-label="Copy log"
                    className={className}
                    data-attr="logs-viewer-copy-menu-open"
                />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem asChild>
                    <ButtonPrimitive
                        menuItem
                        onClick={() => copyLogMessage(log)}
                        data-attr="logs-viewer-copy-message-body"
                    >
                        <IconCopy />
                        Copy message
                    </ButtonPrimitive>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                    <ButtonPrimitive menuItem onClick={() => copyLogRaw(log)} data-attr="logs-viewer-copy-message-raw">
                        <IconCopy />
                        Copy raw
                    </ButtonPrimitive>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
