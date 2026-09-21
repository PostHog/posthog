import type { ReactElement } from 'react'

import { DescriptionList } from '@posthog/mcp-ui'
import { Badge, Card, CardContent } from '@posthog/quill'

export interface VisionObservationData {
    id: string
    session_id: string
    status: string
    error_reason?: string | null
    scanner_result?: { model_output?: unknown } | null
    recording_subject_email?: string | null
    _posthogUrl?: string
}

export const statusVariant: Record<string, 'success' | 'destructive' | 'warning' | 'default'> = {
    succeeded: 'success',
    failed: 'destructive',
    ineligible: 'warning',
    pending: 'default',
    running: 'default',
}

/** The scanner type decides the shape, so read the fields that exist rather than assuming one. */
export function readOutput(observation: VisionObservationData): Record<string, unknown> | null {
    const output = observation.scanner_result?.model_output
    return output && typeof output === 'object' ? (output as Record<string, unknown>) : null
}

function readString(output: Record<string, unknown> | null, key: string): string | null {
    const value = output?.[key]
    return typeof value === 'string' && value ? value : null
}

/**
 * One line describing what the scanner found. A monitor's bare verdict ("yes") says nothing on its
 * own, so its reasoning comes first; a row with no result yet says so rather than repeating the
 * session id already shown in its own column.
 */
export function observationHeadline(observation: VisionObservationData): string {
    const output = readOutput(observation)
    const found =
        readString(output, 'title') ??
        readString(output, 'summary') ??
        readString(output, 'reasoning') ??
        readString(output, 'verdict')
    if (found) {
        return found
    }
    if (observation.status === 'pending' || observation.status === 'running') {
        return 'Still watching'
    }
    return humanReason(observation) ?? 'No result'
}

/** Error reasons are stored as `kind:message`; the message is the half worth showing. */
export function humanReason(observation: VisionObservationData): string | null {
    if (!observation.error_reason) {
        return null
    }
    const separator = observation.error_reason.indexOf(':')
    return separator === -1 ? observation.error_reason : observation.error_reason.slice(separator + 1)
}

export function VisionObservationView({ data }: { data: VisionObservationData }): ReactElement {
    const output = readOutput(data)
    const summary = readString(output, 'summary')
    const reasoning = readString(output, 'reasoning')
    const title = readString(output, 'title')

    const items = [
        { label: 'Session', value: data.session_id },
        { label: 'Status', value: data.status },
    ]
    if (data.recording_subject_email) {
        items.push({ label: 'Person', value: data.recording_subject_email })
    }
    const reason = humanReason(data)
    if (reason) {
        items.push({ label: 'Reason', value: reason })
    }

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-lg font-semibold break-all">{title ?? data.session_id}</span>
                    <Badge variant={statusVariant[data.status] ?? 'default'}>{data.status}</Badge>
                </div>

                {(summary || reasoning) && (
                    <Card>
                        <CardContent>
                            <p className="m-0 text-sm whitespace-pre-wrap">{summary ?? reasoning}</p>
                        </CardContent>
                    </Card>
                )}

                <Card>
                    <CardContent>
                        <DescriptionList items={items} />
                    </CardContent>
                </Card>
            </div>
        </div>
    )
}
