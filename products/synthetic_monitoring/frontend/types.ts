import { WithAccessControl } from '~/types'

export enum SyntheticMonitoringRegion {
    US_EAST_1 = 'us-east-1', // US East (N. Virginia)
    US_WEST_2 = 'us-west-2', // US West (Oregon)
    EU_WEST_1 = 'eu-west-1', // EU West (Ireland)
    EU_CENTRAL_1 = 'eu-central-1', // EU Central (Frankfurt)
    AP_NORTHEAST_1 = 'ap-northeast-2', // Asia Pacific (Seoul)
    SA_EAST_1 = 'sa-east-1', // South America (São Paulo)
}

export enum MonitorState {
    Healthy = 'healthy',
    Failing = 'failing',
    Error = 'error',
    Disabled = 'disabled',
}

export interface SyntheticMonitor extends WithAccessControl {
    id: string
    name: string
    url: string
    frequency_minutes: 1 | 5 | 15 | 30 | 60
    regions: SyntheticMonitoringRegion[]
    method: string
    headers: Record<string, string> | null
    body: string | null
    expected_status_code: number
    timeout_seconds: number
    enabled: boolean
    failure_sparkline: number[]
    response_time_sparkline: number[]
    created_by: {
        id: string
        uuid: string
        distinct_id: string
        first_name: string
        email: string
    } | null
    created_at: string
    updated_at: string
}

export interface SyntheticMonitorCheckEvent {
    monitor_id: string
    monitor_name: string
    url: string
    method: string
    region: string
    success: boolean
    status_code: number | null
    response_time_ms: number | null
    error_message: string | null
    expected_status_code: number
    consecutive_failures: number
    timestamp: string
}
