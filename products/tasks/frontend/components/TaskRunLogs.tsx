import { Spinner } from '@posthog/lemon-ui'

export interface TaskRunLogsProps {
    logs: string
    loading: boolean
}

interface ParsedLogLine {
    timestamp?: string
    level?: string
    message: string
    isRaw: boolean
}

const parseLogLine = (line: string): ParsedLogLine => {
    try {
        const parsed = JSON.parse(line)
        return {
            timestamp: parsed.timestamp || parsed.time,
            level: parsed.level || parsed.severity,
            message: parsed.message || parsed.msg || JSON.stringify(parsed),
            isRaw: false,
        }
    } catch {
        return {
            message: line,
            isRaw: true,
        }
    }
}

const getLevelColor = (level?: string): string => {
    if (!level) {
        return 'text-default'
    }

    const colors: Record<string, string> = {
        error: 'text-danger',
        warn: 'text-warning',
        warning: 'text-warning',
        info: 'text-primary-3000',
        debug: 'text-muted',
    }

    return colors[level.toLowerCase()] || 'text-default'
}

const LogLine = ({ line, index }: { line: string; index: number }): JSX.Element => {
    const parsed = parseLogLine(line)

    if (parsed.isRaw) {
        return (
            <div key={index} className="py-0.5">
                {parsed.message}
            </div>
        )
    }

    return (
        <div key={index} className="py-0.5 flex gap-2">
            {parsed.timestamp && (
                <span className="text-muted shrink-0">{new Date(parsed.timestamp).toLocaleTimeString()}</span>
            )}
            {parsed.level && (
                <span className={`${getLevelColor(parsed.level)} shrink-0 uppercase`}>[{parsed.level}]</span>
            )}
            <span className="flex-1">{parsed.message}</span>
        </div>
    )
}

export function TaskRunLogs({ logs, loading }: TaskRunLogsProps): JSX.Element {
    if (loading) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner />
            </div>
        )
    }

    if (!logs) {
        return (
            <div className="p-4 text-center text-muted">
                <p>No logs available</p>
            </div>
        )
    }

    const logLines = logs.split('\n').filter((line) => line.trim())

    return (
        <div className="p-4">
            <pre className="bg-bg-3000 text-default p-4 rounded overflow-auto font-mono text-xs">
                {logLines.map((line, index) => (
                    <LogLine key={index} line={line} index={index} />
                ))}
            </pre>
        </div>
    )
}
