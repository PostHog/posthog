import { JSX } from 'react'

import { stripAnsi } from '../strip-ansi'

interface ConsoleMessageProps {
    level: 'info' | 'debug' | 'warn' | 'error'
    message: string
    timestamp?: number
}

function getLevelColor(level: ConsoleMessageProps['level']): string {
    switch (level) {
        case 'error':
            return 'text-danger'
        case 'warn':
            return 'text-warning'
        case 'debug':
            return 'text-accent'
        default:
            return 'text-muted'
    }
}

function formatTimestamp(timestamp: number): string {
    return new Date(timestamp).toLocaleTimeString()
}

export function ConsoleMessage({ level, message, timestamp }: ConsoleMessageProps): JSX.Element {
    return (
        <div className="border-l-2 border-border py-0.5 pl-3">
            <span className="text-[13px] text-muted">
                {timestamp !== undefined && <span className="mr-1 text-muted">{formatTimestamp(timestamp)}</span>}
                <span className={getLevelColor(level)}>[{level}]</span> {stripAnsi(message)}
            </span>
        </div>
    )
}
