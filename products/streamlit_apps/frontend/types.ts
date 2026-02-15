import { UserBasicType } from '~/types'

export type StreamlitAppStatus = 'starting' | 'running' | 'stopping' | 'stopped' | 'error'

export interface StreamlitAppVersion {
    id: string
    version_number: number
    zip_file: string
    zip_hash: string
    has_requirements: boolean
    packages: string[]
    snapshot_id: string | null
    created_by: UserBasicType | null
    created_at: string
}

export interface StreamlitAppSandbox {
    status: StreamlitAppStatus
    restart_count: number
    last_error: string
    started_at: string | null
    last_activity_at: string | null
    current_viewers: number
    max_viewers: number
}

export interface StreamlitAppType {
    id: string
    short_id: string
    name: string
    description: string
    cpu_cores: number
    memory_gb: number
    active_version: StreamlitAppVersion | null
    sandbox: StreamlitAppSandbox | null
    status: StreamlitAppStatus
    current_viewers: number
    created_by: UserBasicType | null
    created_at: string
    updated_at: string
}

export interface StreamlitAppMinimalType {
    id: string
    short_id: string
    name: string
    description: string
    cpu_cores: number
    memory_gb: number
    status: StreamlitAppStatus
    current_viewers: number
    created_by: UserBasicType | null
    created_at: string
    updated_at: string
}

export interface StreamlitAppConnectUrl {
    url: string
    token: string
}
