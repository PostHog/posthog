import { type ReactElement } from 'react'

import { DescriptionList } from '@posthog/mcp-ui'
import { Badge, Card, CardContent } from '@posthog/quill'

export interface SessionRecordingData {
    id: string
    distinct_id?: string | null
    viewed?: boolean
    recording_duration?: number
    active_seconds?: number | null
    inactive_seconds?: number | null
    start_time?: string | null
    end_time?: string | null
    click_count?: number | null
    keypress_count?: number | null
    mouse_activity_count?: number | null
    console_log_count?: number | null
    console_warn_count?: number | null
    console_error_count?: number | null
    start_url?: string | null
    snapshot_source?: string | null
    ongoing?: boolean
    activity_score?: number | null
    has_summary?: boolean
    person?: {
        id?: number | string | null
        distinct_ids?: string[]
        properties?: Record<string, unknown> | null
    } | null
    _posthogUrl?: string
}

function userRowDisplayValue(recording: SessionRecordingData): string | null {
    const props = recording.person?.properties
    if (props) {
        for (const key of ['email', '$email'] as const) {
            const v = props[key]
            if (typeof v === 'string' && v.trim()) {
                return v.trim()
            }
        }
    }
    const personId = recording.person?.id
    if (personId != null && personId !== '') {
        return String(personId)
    }
    if (recording.distinct_id) {
        return recording.distinct_id
    }
    return null
}

const startedUtcFormatter = new Intl.DateTimeFormat('en-US', {
    timeZone: 'UTC',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
})

function formatStartedUtc(iso: string): string {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) {
        return '\u2014'
    }
    return `${startedUtcFormatter.format(d)} UTC`
}

function formatDuration(seconds?: number | null): string {
    if (seconds == null) {
        return '\u2014'
    }
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    if (mins > 0) {
        return `${mins}m ${secs}s`
    }
    return `${secs}s`
}

export function SessionRecordingView({ recording }: { recording: SessionRecordingData }): ReactElement {
    const errors = recording.console_error_count ?? 0
    const warns = recording.console_warn_count ?? 0
    const logs = recording.console_log_count ?? 0
    const userDisplay = userRowDisplayValue(recording)

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold">Session Recording</span>
                        {recording.ongoing ? (
                            <Badge variant="warning">Live</Badge>
                        ) : (
                            <Badge variant="success">{formatDuration(recording.recording_duration)}</Badge>
                        )}
                        {recording.viewed !== undefined && (
                            <Badge variant={recording.viewed ? 'default' : 'success'}>
                                {recording.viewed ? 'Viewed' : 'New'}
                            </Badge>
                        )}
                        {recording.snapshot_source && <Badge>{recording.snapshot_source}</Badge>}
                    </div>
                    <span className="text-xs font-mono text-muted-foreground">{recording.id}</span>
                </div>

                <Card>
                    <CardContent>
                        <DescriptionList
                            items={[
                                {
                                    label: 'Started',
                                    value: recording.start_time ? formatStartedUtc(recording.start_time) : '\u2014',
                                },
                                { label: 'Active time', value: formatDuration(recording.active_seconds) },
                                ...(recording.start_url
                                    ? [
                                          {
                                              label: 'Start URL',
                                              value: (
                                                  <span className="block truncate" title={recording.start_url}>
                                                      {recording.start_url}
                                                  </span>
                                              ),
                                          },
                                      ]
                                    : []),
                                ...(userDisplay
                                    ? [
                                          {
                                              label: 'User',
                                              value: (
                                                  <span className="block truncate" title={userDisplay}>
                                                      {userDisplay}
                                                  </span>
                                              ),
                                          },
                                      ]
                                    : []),
                            ]}
                        />
                    </CardContent>
                </Card>

                <Card>
                    <CardContent>
                        <div className="flex">
                            <div className="flex-1 min-w-0 pr-6">
                                <span className="text-sm font-semibold">Interactions</span>
                                <div className="mt-3 w-4/5 max-w-full mx-auto flex flex-row justify-between">
                                    <Stat label="Clicks" value={recording.click_count ?? 0} />
                                    <Stat label="Keypresses" value={recording.keypress_count ?? 0} />
                                    <Stat label="Mouse events" value={recording.mouse_activity_count ?? 0} />
                                </div>
                            </div>
                            <div className="flex-1 min-w-0 pl-6 border-l">
                                <span className="text-sm font-semibold">Console output</span>
                                <div className="mt-3 w-4/5 max-w-full mx-auto flex flex-row justify-between">
                                    <Stat label="Errors" value={errors} />
                                    <Stat label="Warnings" value={warns} />
                                    <Stat label="Logs" value={logs} />
                                </div>
                            </div>
                        </div>
                    </CardContent>
                </Card>
            </div>
        </div>
    )
}

function Stat({ label, value }: { label: string; value: number | string }): ReactElement {
    return (
        <div className="text-center">
            <div className="text-xl font-semibold">{value}</div>
            <div className="text-xs text-muted-foreground mt-0.5">{label}</div>
        </div>
    )
}
