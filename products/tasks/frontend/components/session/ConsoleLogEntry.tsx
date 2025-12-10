import { LemonTag } from '@posthog/lemon-ui'

import { LogLevel } from '../../lib/parse-logs'

interface ConsoleLogEntryProps {
    level: LogLevel
    message: string
    timestamp?: string
}

const LEVEL_CONFIG: Record<LogLevel, { type: 'default' | 'warning' | 'danger' | 'highlight' }> = {
    info: { type: 'default' },
    debug: { type: 'highlight' },
    warn: { type: 'warning' },
    error: { type: 'danger' },
}

export function ConsoleLogEntry({ level, message, timestamp }: ConsoleLogEntryProps): JSX.Element {
    const config = LEVEL_CONFIG[level]

    return (
        <div className="flex items-start gap-2 py-2">
            {timestamp && (
                <span className="text-xs text-muted shrink-0">{new Date(timestamp).toLocaleTimeString()}</span>
            )}
            <LemonTag type={config.type} size="small" className="shrink-0 uppercase">
                {level}
            </LemonTag>
            <span className="text-sm flex-1 break-words">{message}</span>
        </div>
    )
}
