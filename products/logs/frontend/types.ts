import { integer } from '~/queries/schema/type-utils'

export interface LogMessage {
    uuid: string
    team_id: integer
    trace_id: string
    span_id: string
    body: string
    attributes: Record<string, string>
    timestamp: string
    observed_timestamp: string
    severity_text: 'debug' | 'info' | 'warn' | 'error'
    resource: string
}
