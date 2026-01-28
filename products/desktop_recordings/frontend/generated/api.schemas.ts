/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `zoom` - Zoom
 * `teams` - Microsoft Teams
 * `meet` - Google Meet
 * `desktop_audio` - Desktop audio
 * `slack` - Slack huddle
 */
export type Platform9aaEnumApi = (typeof Platform9aaEnumApi)[keyof typeof Platform9aaEnumApi]

export const Platform9aaEnumApi = {
    zoom: 'zoom',
    teams: 'teams',
    meet: 'meet',
    desktop_audio: 'desktop_audio',
    slack: 'slack',
} as const

/**
 * * `recording` - Recording
 * `uploading` - Uploading
 * `processing` - Processing
 * `ready` - Ready
 * `error` - Error
 */
export type Status292EnumApi = (typeof Status292EnumApi)[keyof typeof Status292EnumApi]

export const Status292EnumApi = {
    recording: 'recording',
    uploading: 'uploading',
    processing: 'processing',
    ready: 'ready',
    error: 'error',
} as const

/**
 * Serializer for individual transcript segments from AssemblyAI
 */
export interface TranscriptSegmentApi {
    /**
     * Milliseconds from recording start
     * @nullable
     */
    timestamp?: number | null
    /** @nullable */
    speaker?: string | null
    text: string
    /**
     * Transcription confidence score
     * @nullable
     */
    confidence?: number | null
    /**
     * Whether this is the final version
     * @nullable
     */
    is_final?: boolean | null
}

/**
 * Serializer for extracted tasks
 */
export interface TaskApi {
    title: string
    description?: string
    /** @nullable */
    assignee?: string | null
}

export interface DesktopRecordingApi {
    readonly id: string
    readonly team: number
    /** @nullable */
    readonly created_by: number | null
    readonly sdk_upload_id: string
    /** @nullable */
    recall_recording_id?: string | null
    platform: Platform9aaEnumApi
    /**
     * @maxLength 255
     * @nullable
     */
    meeting_title?: string | null
    /**
     * @maxLength 200
     * @nullable
     */
    meeting_url?: string | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    duration_seconds?: number | null
    status?: Status292EnumApi
    /** @nullable */
    notes?: string | null
    /** @nullable */
    error_message?: string | null
    /**
     * @maxLength 200
     * @nullable
     */
    video_url?: string | null
    /**
     * @minimum -9223372036854776000
     * @maximum 9223372036854776000
     * @nullable
     */
    video_size_bytes?: number | null
    /** List of participant names */
    participants?: string[]
    readonly transcript_text: string
    /** Transcript segments with timestamps */
    transcript_segments?: TranscriptSegmentApi[]
    /** @nullable */
    summary?: string | null
    /** AI-extracted tasks from transcript */
    extracted_tasks?: TaskApi[]
    /** @nullable */
    tasks_generated_at?: string | null
    /** @nullable */
    summary_generated_at?: string | null
    started_at?: string
    /** @nullable */
    completed_at?: string | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedDesktopRecordingListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DesktopRecordingApi[]
}

/**
 * * `zoom` - zoom
 * `teams` - teams
 * `meet` - meet
 * `desktop_audio` - desktop_audio
 * `slack` - slack
 */
export type CreateRecordingRequestPlatformEnumApi =
    (typeof CreateRecordingRequestPlatformEnumApi)[keyof typeof CreateRecordingRequestPlatformEnumApi]

export const CreateRecordingRequestPlatformEnumApi = {
    zoom: 'zoom',
    teams: 'teams',
    meet: 'meet',
    desktop_audio: 'desktop_audio',
    slack: 'slack',
} as const

/**
 * Request body for creating a new recording
 */
export interface CreateRecordingRequestApi {
    /** Meeting platform being recorded

* `zoom` - zoom
* `teams` - teams
* `meet` - meet
* `desktop_audio` - desktop_audio
* `slack` - slack */
    platform?: CreateRecordingRequestPlatformEnumApi
}

/**
 * Response for creating a new recording (includes upload_token)
 */
export interface CreateRecordingResponseApi {
    readonly id: string
    readonly team: number
    /** @nullable */
    readonly created_by: number | null
    readonly sdk_upload_id: string
    /** @nullable */
    recall_recording_id?: string | null
    platform: Platform9aaEnumApi
    /**
     * @maxLength 255
     * @nullable
     */
    meeting_title?: string | null
    /**
     * @maxLength 200
     * @nullable
     */
    meeting_url?: string | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    duration_seconds?: number | null
    status?: Status292EnumApi
    /** @nullable */
    notes?: string | null
    /** @nullable */
    error_message?: string | null
    /**
     * @maxLength 200
     * @nullable
     */
    video_url?: string | null
    /**
     * @minimum -9223372036854776000
     * @maximum 9223372036854776000
     * @nullable
     */
    video_size_bytes?: number | null
    /** List of participant names */
    participants?: string[]
    readonly transcript_text: string
    /** Transcript segments with timestamps */
    transcript_segments?: TranscriptSegmentApi[]
    /** @nullable */
    summary?: string | null
    /** AI-extracted tasks from transcript */
    extracted_tasks?: TaskApi[]
    /** @nullable */
    tasks_generated_at?: string | null
    /** @nullable */
    summary_generated_at?: string | null
    started_at?: string
    /** @nullable */
    completed_at?: string | null
    readonly created_at: string
    readonly updated_at: string
    /** Recall.ai upload token for the desktop SDK */
    upload_token: string
}

export interface PatchedDesktopRecordingApi {
    readonly id?: string
    readonly team?: number
    /** @nullable */
    readonly created_by?: number | null
    readonly sdk_upload_id?: string
    /** @nullable */
    recall_recording_id?: string | null
    platform?: Platform9aaEnumApi
    /**
     * @maxLength 255
     * @nullable
     */
    meeting_title?: string | null
    /**
     * @maxLength 200
     * @nullable
     */
    meeting_url?: string | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    duration_seconds?: number | null
    status?: Status292EnumApi
    /** @nullable */
    notes?: string | null
    /** @nullable */
    error_message?: string | null
    /**
     * @maxLength 200
     * @nullable
     */
    video_url?: string | null
    /**
     * @minimum -9223372036854776000
     * @maximum 9223372036854776000
     * @nullable
     */
    video_size_bytes?: number | null
    /** List of participant names */
    participants?: string[]
    readonly transcript_text?: string
    /** Transcript segments with timestamps */
    transcript_segments?: TranscriptSegmentApi[]
    /** @nullable */
    summary?: string | null
    /** AI-extracted tasks from transcript */
    extracted_tasks?: TaskApi[]
    /** @nullable */
    tasks_generated_at?: string | null
    /** @nullable */
    summary_generated_at?: string | null
    started_at?: string
    /** @nullable */
    completed_at?: string | null
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * Serializer for appending transcript segments (supports batched real-time uploads)
 */
export interface AppendSegmentsApi {
    /** @minItems 1 */
    segments: TranscriptSegmentApi[]
}

export type DesktopRecordingsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
