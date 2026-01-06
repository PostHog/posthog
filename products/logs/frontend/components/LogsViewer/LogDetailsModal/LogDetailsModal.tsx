import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonModal } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'
import { TZLabel } from 'lib/components/TZLabel'

import { logDetailsModalLogic } from './logDetailsModalLogic'

const SEVERITY_COLORS: Record<string, string> = {
    trace: 'bg-muted-alt',
    debug: 'bg-muted',
    info: 'bg-brand-blue',
    warn: 'bg-warning',
    error: 'bg-danger',
    fatal: 'bg-danger-dark',
}

// Deep parse all string fields that look like JSON
function parseJsonFields(obj: unknown): unknown {
    if (typeof obj === 'string') {
        try {
            const parsed = JSON.parse(obj)
            return parseJsonFields(parsed)
        } catch {
            return obj
        }
    }
    if (Array.isArray(obj)) {
        return obj.map(parseJsonFields)
    }
    if (obj !== null && typeof obj === 'object') {
        const result: Record<string, unknown> = {}
        for (const [key, value] of Object.entries(obj)) {
            result[key] = parseJsonFields(value)
        }
        return result
    }
    return obj
}

interface LogDetailsModalProps {
    timezone: string
}

export function LogDetailsModal({ timezone }: LogDetailsModalProps): JSX.Element | null {
    const { isOpen, selectedLog, jsonParseAllFields } = useValues(logDetailsModalLogic)
    const { closeLogDetails, setJsonParseAllFields } = useActions(logDetailsModalLogic)

    if (!selectedLog) {
        return null
    }

    const severityColor = SEVERITY_COLORS[selectedLog.severity_text] ?? 'bg-muted-3000'
    const displayData = jsonParseAllFields
        ? (parseJsonFields(selectedLog.originalLog) as object)
        : selectedLog.originalLog

    return (
        <LemonModal
            title="Log details"
            isOpen={isOpen}
            onClose={closeLogDetails}
            simple
            overlayClassName="backdrop-blur-none flex items-stretch justify-end pr-16 py-4 pointer-events-none h-screen"
            className="m-0! max-w-3xl w-[50vw] pointer-events-auto min-h-full"
        >
            <div className="flex flex-col h-full">
                <LemonModal.Header className="flex flex-col gap-2">
                    <h3>Log details</h3>
                    <div className="flex items-center gap-6">
                        <div className="flex items-center gap-2">
                            <span className="text-muted text-xs font-semibold uppercase">Timestamp</span>
                            <span className="text-xs font-mono">
                                <TZLabel
                                    time={selectedLog.timestamp}
                                    formatDate="YYYY-MM-DD"
                                    formatTime="HH:mm:ss.SSS"
                                    displayTimezone={timezone}
                                    timestampStyle="absolute"
                                />
                            </span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-muted text-xs font-semibold uppercase">Severity</span>
                            <div className="flex items-center gap-1.5">
                                <div className={`w-2 h-2 rounded-full ${severityColor}`} />
                                <span className="font-mono text-xs">{selectedLog.severity_text.toUpperCase()}</span>
                            </div>
                        </div>
                    </div>
                </LemonModal.Header>
                <LemonModal.Content>
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center">
                            <LemonCheckbox
                                checked={jsonParseAllFields}
                                onChange={setJsonParseAllFields}
                                label="JSON parse all fields"
                                size="small"
                            />
                        </div>
                        <div className="p-2 bg-bg-light rounded overflow-auto">
                            <JSONViewer src={displayData} collapsed={2} sortKeys />
                        </div>
                    </div>
                </LemonModal.Content>
            </div>
        </LemonModal>
    )
}
