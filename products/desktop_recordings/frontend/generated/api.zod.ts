/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export const desktopRecordingsListResponseResultsItemMeetingTitleMax = 255

export const desktopRecordingsListResponseResultsItemMeetingUrlMax = 200

export const desktopRecordingsListResponseResultsItemDurationSecondsMin = -2147483648
export const desktopRecordingsListResponseResultsItemDurationSecondsMax = 2147483647

export const desktopRecordingsListResponseResultsItemVideoUrlMax = 200

export const desktopRecordingsListResponseResultsItemVideoSizeBytesMin = -9223372036854776000
export const desktopRecordingsListResponseResultsItemVideoSizeBytesMax = 9223372036854776000

export const DesktopRecordingsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            team: zod.number(),
            created_by: zod.number().nullable(),
            sdk_upload_id: zod.uuid(),
            recall_recording_id: zod.uuid().nullish(),
            platform: zod
                .enum(['zoom', 'teams', 'meet', 'desktop_audio', 'slack'])
                .describe(
                    '* `zoom` - Zoom\n* `teams` - Microsoft Teams\n* `meet` - Google Meet\n* `desktop_audio` - Desktop audio\n* `slack` - Slack huddle'
                ),
            meeting_title: zod.string().max(desktopRecordingsListResponseResultsItemMeetingTitleMax).nullish(),
            meeting_url: zod.url().max(desktopRecordingsListResponseResultsItemMeetingUrlMax).nullish(),
            duration_seconds: zod
                .number()
                .min(desktopRecordingsListResponseResultsItemDurationSecondsMin)
                .max(desktopRecordingsListResponseResultsItemDurationSecondsMax)
                .nullish(),
            status: zod
                .enum(['recording', 'uploading', 'processing', 'ready', 'error'])
                .optional()
                .describe(
                    '* `recording` - Recording\n* `uploading` - Uploading\n* `processing` - Processing\n* `ready` - Ready\n* `error` - Error'
                ),
            notes: zod.string().nullish(),
            error_message: zod.string().nullish(),
            video_url: zod.url().max(desktopRecordingsListResponseResultsItemVideoUrlMax).nullish(),
            video_size_bytes: zod
                .number()
                .min(desktopRecordingsListResponseResultsItemVideoSizeBytesMin)
                .max(desktopRecordingsListResponseResultsItemVideoSizeBytesMax)
                .nullish(),
            participants: zod.array(zod.string()).optional().describe('List of participant names'),
            transcript_text: zod.string(),
            transcript_segments: zod
                .array(
                    zod
                        .object({
                            timestamp: zod.number().nullish().describe('Milliseconds from recording start'),
                            speaker: zod.string().nullish(),
                            text: zod.string(),
                            confidence: zod.number().nullish().describe('Transcription confidence score'),
                            is_final: zod.boolean().nullish().describe('Whether this is the final version'),
                        })
                        .describe('Serializer for individual transcript segments from AssemblyAI')
                )
                .optional()
                .describe('Transcript segments with timestamps'),
            summary: zod.string().nullish(),
            extracted_tasks: zod
                .array(
                    zod
                        .object({
                            title: zod.string(),
                            description: zod.string().optional(),
                            assignee: zod.string().nullish(),
                        })
                        .describe('Serializer for extracted tasks')
                )
                .optional()
                .describe('AI-extracted tasks from transcript'),
            tasks_generated_at: zod.iso.datetime({}).nullish(),
            summary_generated_at: zod.iso.datetime({}).nullish(),
            started_at: zod.iso.datetime({}).optional(),
            completed_at: zod.iso.datetime({}).nullish(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
})

/**
 * Create a new recording and get Recall.ai upload token for the desktop SDK
 */
export const desktopRecordingsCreateBodyPlatformDefault = `desktop_audio`

export const DesktopRecordingsCreateBody = /* @__PURE__ */ zod
    .object({
        platform: zod
            .enum(['zoom', 'teams', 'meet', 'desktop_audio', 'slack'])
            .describe(
                '* `zoom` - zoom\n* `teams` - teams\n* `meet` - meet\n* `desktop_audio` - desktop_audio\n* `slack` - slack'
            )
            .default(desktopRecordingsCreateBodyPlatformDefault)
            .describe(
                'Meeting platform being recorded\n\n* `zoom` - zoom\n* `teams` - teams\n* `meet` - meet\n* `desktop_audio` - desktop_audio\n* `slack` - slack'
            ),
    })
    .describe('Request body for creating a new recording')

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export const desktopRecordingsRetrieveResponseMeetingTitleMax = 255

export const desktopRecordingsRetrieveResponseMeetingUrlMax = 200

export const desktopRecordingsRetrieveResponseDurationSecondsMin = -2147483648
export const desktopRecordingsRetrieveResponseDurationSecondsMax = 2147483647

export const desktopRecordingsRetrieveResponseVideoUrlMax = 200

export const desktopRecordingsRetrieveResponseVideoSizeBytesMin = -9223372036854776000
export const desktopRecordingsRetrieveResponseVideoSizeBytesMax = 9223372036854776000

export const DesktopRecordingsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    team: zod.number(),
    created_by: zod.number().nullable(),
    sdk_upload_id: zod.uuid(),
    recall_recording_id: zod.uuid().nullish(),
    platform: zod
        .enum(['zoom', 'teams', 'meet', 'desktop_audio', 'slack'])
        .describe(
            '* `zoom` - Zoom\n* `teams` - Microsoft Teams\n* `meet` - Google Meet\n* `desktop_audio` - Desktop audio\n* `slack` - Slack huddle'
        ),
    meeting_title: zod.string().max(desktopRecordingsRetrieveResponseMeetingTitleMax).nullish(),
    meeting_url: zod.url().max(desktopRecordingsRetrieveResponseMeetingUrlMax).nullish(),
    duration_seconds: zod
        .number()
        .min(desktopRecordingsRetrieveResponseDurationSecondsMin)
        .max(desktopRecordingsRetrieveResponseDurationSecondsMax)
        .nullish(),
    status: zod
        .enum(['recording', 'uploading', 'processing', 'ready', 'error'])
        .optional()
        .describe(
            '* `recording` - Recording\n* `uploading` - Uploading\n* `processing` - Processing\n* `ready` - Ready\n* `error` - Error'
        ),
    notes: zod.string().nullish(),
    error_message: zod.string().nullish(),
    video_url: zod.url().max(desktopRecordingsRetrieveResponseVideoUrlMax).nullish(),
    video_size_bytes: zod
        .number()
        .min(desktopRecordingsRetrieveResponseVideoSizeBytesMin)
        .max(desktopRecordingsRetrieveResponseVideoSizeBytesMax)
        .nullish(),
    participants: zod.array(zod.string()).optional().describe('List of participant names'),
    transcript_text: zod.string(),
    transcript_segments: zod
        .array(
            zod
                .object({
                    timestamp: zod.number().nullish().describe('Milliseconds from recording start'),
                    speaker: zod.string().nullish(),
                    text: zod.string(),
                    confidence: zod.number().nullish().describe('Transcription confidence score'),
                    is_final: zod.boolean().nullish().describe('Whether this is the final version'),
                })
                .describe('Serializer for individual transcript segments from AssemblyAI')
        )
        .optional()
        .describe('Transcript segments with timestamps'),
    summary: zod.string().nullish(),
    extracted_tasks: zod
        .array(
            zod
                .object({
                    title: zod.string(),
                    description: zod.string().optional(),
                    assignee: zod.string().nullish(),
                })
                .describe('Serializer for extracted tasks')
        )
        .optional()
        .describe('AI-extracted tasks from transcript'),
    tasks_generated_at: zod.iso.datetime({}).nullish(),
    summary_generated_at: zod.iso.datetime({}).nullish(),
    started_at: zod.iso.datetime({}).optional(),
    completed_at: zod.iso.datetime({}).nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export const desktopRecordingsUpdateBodyMeetingTitleMax = 255

export const desktopRecordingsUpdateBodyMeetingUrlMax = 200

export const desktopRecordingsUpdateBodyDurationSecondsMin = -2147483648
export const desktopRecordingsUpdateBodyDurationSecondsMax = 2147483647

export const desktopRecordingsUpdateBodyVideoUrlMax = 200

export const desktopRecordingsUpdateBodyVideoSizeBytesMin = -9223372036854776000
export const desktopRecordingsUpdateBodyVideoSizeBytesMax = 9223372036854776000

export const DesktopRecordingsUpdateBody = /* @__PURE__ */ zod.object({
    recall_recording_id: zod.uuid().nullish(),
    platform: zod
        .enum(['zoom', 'teams', 'meet', 'desktop_audio', 'slack'])
        .describe(
            '* `zoom` - Zoom\n* `teams` - Microsoft Teams\n* `meet` - Google Meet\n* `desktop_audio` - Desktop audio\n* `slack` - Slack huddle'
        ),
    meeting_title: zod.string().max(desktopRecordingsUpdateBodyMeetingTitleMax).nullish(),
    meeting_url: zod.url().max(desktopRecordingsUpdateBodyMeetingUrlMax).nullish(),
    duration_seconds: zod
        .number()
        .min(desktopRecordingsUpdateBodyDurationSecondsMin)
        .max(desktopRecordingsUpdateBodyDurationSecondsMax)
        .nullish(),
    status: zod
        .enum(['recording', 'uploading', 'processing', 'ready', 'error'])
        .optional()
        .describe(
            '* `recording` - Recording\n* `uploading` - Uploading\n* `processing` - Processing\n* `ready` - Ready\n* `error` - Error'
        ),
    notes: zod.string().nullish(),
    error_message: zod.string().nullish(),
    video_url: zod.url().max(desktopRecordingsUpdateBodyVideoUrlMax).nullish(),
    video_size_bytes: zod
        .number()
        .min(desktopRecordingsUpdateBodyVideoSizeBytesMin)
        .max(desktopRecordingsUpdateBodyVideoSizeBytesMax)
        .nullish(),
    participants: zod.array(zod.string()).optional().describe('List of participant names'),
    transcript_segments: zod
        .array(
            zod
                .object({
                    timestamp: zod.number().nullish().describe('Milliseconds from recording start'),
                    speaker: zod.string().nullish(),
                    text: zod.string(),
                    confidence: zod.number().nullish().describe('Transcription confidence score'),
                    is_final: zod.boolean().nullish().describe('Whether this is the final version'),
                })
                .describe('Serializer for individual transcript segments from AssemblyAI')
        )
        .optional()
        .describe('Transcript segments with timestamps'),
    summary: zod.string().nullish(),
    extracted_tasks: zod
        .array(
            zod
                .object({
                    title: zod.string(),
                    description: zod.string().optional(),
                    assignee: zod.string().nullish(),
                })
                .describe('Serializer for extracted tasks')
        )
        .optional()
        .describe('AI-extracted tasks from transcript'),
    tasks_generated_at: zod.iso.datetime({}).nullish(),
    summary_generated_at: zod.iso.datetime({}).nullish(),
    started_at: zod.iso.datetime({}).optional(),
    completed_at: zod.iso.datetime({}).nullish(),
})

export const desktopRecordingsUpdateResponseMeetingTitleMax = 255

export const desktopRecordingsUpdateResponseMeetingUrlMax = 200

export const desktopRecordingsUpdateResponseDurationSecondsMin = -2147483648
export const desktopRecordingsUpdateResponseDurationSecondsMax = 2147483647

export const desktopRecordingsUpdateResponseVideoUrlMax = 200

export const desktopRecordingsUpdateResponseVideoSizeBytesMin = -9223372036854776000
export const desktopRecordingsUpdateResponseVideoSizeBytesMax = 9223372036854776000

export const DesktopRecordingsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    team: zod.number(),
    created_by: zod.number().nullable(),
    sdk_upload_id: zod.uuid(),
    recall_recording_id: zod.uuid().nullish(),
    platform: zod
        .enum(['zoom', 'teams', 'meet', 'desktop_audio', 'slack'])
        .describe(
            '* `zoom` - Zoom\n* `teams` - Microsoft Teams\n* `meet` - Google Meet\n* `desktop_audio` - Desktop audio\n* `slack` - Slack huddle'
        ),
    meeting_title: zod.string().max(desktopRecordingsUpdateResponseMeetingTitleMax).nullish(),
    meeting_url: zod.url().max(desktopRecordingsUpdateResponseMeetingUrlMax).nullish(),
    duration_seconds: zod
        .number()
        .min(desktopRecordingsUpdateResponseDurationSecondsMin)
        .max(desktopRecordingsUpdateResponseDurationSecondsMax)
        .nullish(),
    status: zod
        .enum(['recording', 'uploading', 'processing', 'ready', 'error'])
        .optional()
        .describe(
            '* `recording` - Recording\n* `uploading` - Uploading\n* `processing` - Processing\n* `ready` - Ready\n* `error` - Error'
        ),
    notes: zod.string().nullish(),
    error_message: zod.string().nullish(),
    video_url: zod.url().max(desktopRecordingsUpdateResponseVideoUrlMax).nullish(),
    video_size_bytes: zod
        .number()
        .min(desktopRecordingsUpdateResponseVideoSizeBytesMin)
        .max(desktopRecordingsUpdateResponseVideoSizeBytesMax)
        .nullish(),
    participants: zod.array(zod.string()).optional().describe('List of participant names'),
    transcript_text: zod.string(),
    transcript_segments: zod
        .array(
            zod
                .object({
                    timestamp: zod.number().nullish().describe('Milliseconds from recording start'),
                    speaker: zod.string().nullish(),
                    text: zod.string(),
                    confidence: zod.number().nullish().describe('Transcription confidence score'),
                    is_final: zod.boolean().nullish().describe('Whether this is the final version'),
                })
                .describe('Serializer for individual transcript segments from AssemblyAI')
        )
        .optional()
        .describe('Transcript segments with timestamps'),
    summary: zod.string().nullish(),
    extracted_tasks: zod
        .array(
            zod
                .object({
                    title: zod.string(),
                    description: zod.string().optional(),
                    assignee: zod.string().nullish(),
                })
                .describe('Serializer for extracted tasks')
        )
        .optional()
        .describe('AI-extracted tasks from transcript'),
    tasks_generated_at: zod.iso.datetime({}).nullish(),
    summary_generated_at: zod.iso.datetime({}).nullish(),
    started_at: zod.iso.datetime({}).optional(),
    completed_at: zod.iso.datetime({}).nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export const desktopRecordingsPartialUpdateBodyMeetingTitleMax = 255

export const desktopRecordingsPartialUpdateBodyMeetingUrlMax = 200

export const desktopRecordingsPartialUpdateBodyDurationSecondsMin = -2147483648
export const desktopRecordingsPartialUpdateBodyDurationSecondsMax = 2147483647

export const desktopRecordingsPartialUpdateBodyVideoUrlMax = 200

export const desktopRecordingsPartialUpdateBodyVideoSizeBytesMin = -9223372036854776000
export const desktopRecordingsPartialUpdateBodyVideoSizeBytesMax = 9223372036854776000

export const DesktopRecordingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    recall_recording_id: zod.uuid().nullish(),
    platform: zod
        .enum(['zoom', 'teams', 'meet', 'desktop_audio', 'slack'])
        .optional()
        .describe(
            '* `zoom` - Zoom\n* `teams` - Microsoft Teams\n* `meet` - Google Meet\n* `desktop_audio` - Desktop audio\n* `slack` - Slack huddle'
        ),
    meeting_title: zod.string().max(desktopRecordingsPartialUpdateBodyMeetingTitleMax).nullish(),
    meeting_url: zod.url().max(desktopRecordingsPartialUpdateBodyMeetingUrlMax).nullish(),
    duration_seconds: zod
        .number()
        .min(desktopRecordingsPartialUpdateBodyDurationSecondsMin)
        .max(desktopRecordingsPartialUpdateBodyDurationSecondsMax)
        .nullish(),
    status: zod
        .enum(['recording', 'uploading', 'processing', 'ready', 'error'])
        .optional()
        .describe(
            '* `recording` - Recording\n* `uploading` - Uploading\n* `processing` - Processing\n* `ready` - Ready\n* `error` - Error'
        ),
    notes: zod.string().nullish(),
    error_message: zod.string().nullish(),
    video_url: zod.url().max(desktopRecordingsPartialUpdateBodyVideoUrlMax).nullish(),
    video_size_bytes: zod
        .number()
        .min(desktopRecordingsPartialUpdateBodyVideoSizeBytesMin)
        .max(desktopRecordingsPartialUpdateBodyVideoSizeBytesMax)
        .nullish(),
    participants: zod.array(zod.string()).optional().describe('List of participant names'),
    transcript_segments: zod
        .array(
            zod
                .object({
                    timestamp: zod.number().nullish().describe('Milliseconds from recording start'),
                    speaker: zod.string().nullish(),
                    text: zod.string(),
                    confidence: zod.number().nullish().describe('Transcription confidence score'),
                    is_final: zod.boolean().nullish().describe('Whether this is the final version'),
                })
                .describe('Serializer for individual transcript segments from AssemblyAI')
        )
        .optional()
        .describe('Transcript segments with timestamps'),
    summary: zod.string().nullish(),
    extracted_tasks: zod
        .array(
            zod
                .object({
                    title: zod.string(),
                    description: zod.string().optional(),
                    assignee: zod.string().nullish(),
                })
                .describe('Serializer for extracted tasks')
        )
        .optional()
        .describe('AI-extracted tasks from transcript'),
    tasks_generated_at: zod.iso.datetime({}).nullish(),
    summary_generated_at: zod.iso.datetime({}).nullish(),
    started_at: zod.iso.datetime({}).optional(),
    completed_at: zod.iso.datetime({}).nullish(),
})

export const desktopRecordingsPartialUpdateResponseMeetingTitleMax = 255

export const desktopRecordingsPartialUpdateResponseMeetingUrlMax = 200

export const desktopRecordingsPartialUpdateResponseDurationSecondsMin = -2147483648
export const desktopRecordingsPartialUpdateResponseDurationSecondsMax = 2147483647

export const desktopRecordingsPartialUpdateResponseVideoUrlMax = 200

export const desktopRecordingsPartialUpdateResponseVideoSizeBytesMin = -9223372036854776000
export const desktopRecordingsPartialUpdateResponseVideoSizeBytesMax = 9223372036854776000

export const DesktopRecordingsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    team: zod.number(),
    created_by: zod.number().nullable(),
    sdk_upload_id: zod.uuid(),
    recall_recording_id: zod.uuid().nullish(),
    platform: zod
        .enum(['zoom', 'teams', 'meet', 'desktop_audio', 'slack'])
        .describe(
            '* `zoom` - Zoom\n* `teams` - Microsoft Teams\n* `meet` - Google Meet\n* `desktop_audio` - Desktop audio\n* `slack` - Slack huddle'
        ),
    meeting_title: zod.string().max(desktopRecordingsPartialUpdateResponseMeetingTitleMax).nullish(),
    meeting_url: zod.url().max(desktopRecordingsPartialUpdateResponseMeetingUrlMax).nullish(),
    duration_seconds: zod
        .number()
        .min(desktopRecordingsPartialUpdateResponseDurationSecondsMin)
        .max(desktopRecordingsPartialUpdateResponseDurationSecondsMax)
        .nullish(),
    status: zod
        .enum(['recording', 'uploading', 'processing', 'ready', 'error'])
        .optional()
        .describe(
            '* `recording` - Recording\n* `uploading` - Uploading\n* `processing` - Processing\n* `ready` - Ready\n* `error` - Error'
        ),
    notes: zod.string().nullish(),
    error_message: zod.string().nullish(),
    video_url: zod.url().max(desktopRecordingsPartialUpdateResponseVideoUrlMax).nullish(),
    video_size_bytes: zod
        .number()
        .min(desktopRecordingsPartialUpdateResponseVideoSizeBytesMin)
        .max(desktopRecordingsPartialUpdateResponseVideoSizeBytesMax)
        .nullish(),
    participants: zod.array(zod.string()).optional().describe('List of participant names'),
    transcript_text: zod.string(),
    transcript_segments: zod
        .array(
            zod
                .object({
                    timestamp: zod.number().nullish().describe('Milliseconds from recording start'),
                    speaker: zod.string().nullish(),
                    text: zod.string(),
                    confidence: zod.number().nullish().describe('Transcription confidence score'),
                    is_final: zod.boolean().nullish().describe('Whether this is the final version'),
                })
                .describe('Serializer for individual transcript segments from AssemblyAI')
        )
        .optional()
        .describe('Transcript segments with timestamps'),
    summary: zod.string().nullish(),
    extracted_tasks: zod
        .array(
            zod
                .object({
                    title: zod.string(),
                    description: zod.string().optional(),
                    assignee: zod.string().nullish(),
                })
                .describe('Serializer for extracted tasks')
        )
        .optional()
        .describe('AI-extracted tasks from transcript'),
    tasks_generated_at: zod.iso.datetime({}).nullish(),
    summary_generated_at: zod.iso.datetime({}).nullish(),
    started_at: zod.iso.datetime({}).optional(),
    completed_at: zod.iso.datetime({}).nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

/**
 * Append transcript segments (supports batched real-time streaming)
 */

export const DesktopRecordingsAppendSegmentsCreateBody = /* @__PURE__ */ zod
    .object({
        segments: zod
            .array(
                zod
                    .object({
                        timestamp: zod.number().nullish().describe('Milliseconds from recording start'),
                        speaker: zod.string().nullish(),
                        text: zod.string(),
                        confidence: zod.number().nullish().describe('Transcription confidence score'),
                        is_final: zod.boolean().nullish().describe('Whether this is the final version'),
                    })
                    .describe('Serializer for individual transcript segments from AssemblyAI')
            )
            .min(1),
    })
    .describe('Serializer for appending transcript segments (supports batched real-time uploads)')

export const desktopRecordingsAppendSegmentsCreateResponseMeetingTitleMax = 255

export const desktopRecordingsAppendSegmentsCreateResponseMeetingUrlMax = 200

export const desktopRecordingsAppendSegmentsCreateResponseDurationSecondsMin = -2147483648
export const desktopRecordingsAppendSegmentsCreateResponseDurationSecondsMax = 2147483647

export const desktopRecordingsAppendSegmentsCreateResponseVideoUrlMax = 200

export const desktopRecordingsAppendSegmentsCreateResponseVideoSizeBytesMin = -9223372036854776000
export const desktopRecordingsAppendSegmentsCreateResponseVideoSizeBytesMax = 9223372036854776000

export const DesktopRecordingsAppendSegmentsCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    team: zod.number(),
    created_by: zod.number().nullable(),
    sdk_upload_id: zod.uuid(),
    recall_recording_id: zod.uuid().nullish(),
    platform: zod
        .enum(['zoom', 'teams', 'meet', 'desktop_audio', 'slack'])
        .describe(
            '* `zoom` - Zoom\n* `teams` - Microsoft Teams\n* `meet` - Google Meet\n* `desktop_audio` - Desktop audio\n* `slack` - Slack huddle'
        ),
    meeting_title: zod.string().max(desktopRecordingsAppendSegmentsCreateResponseMeetingTitleMax).nullish(),
    meeting_url: zod.url().max(desktopRecordingsAppendSegmentsCreateResponseMeetingUrlMax).nullish(),
    duration_seconds: zod
        .number()
        .min(desktopRecordingsAppendSegmentsCreateResponseDurationSecondsMin)
        .max(desktopRecordingsAppendSegmentsCreateResponseDurationSecondsMax)
        .nullish(),
    status: zod
        .enum(['recording', 'uploading', 'processing', 'ready', 'error'])
        .optional()
        .describe(
            '* `recording` - Recording\n* `uploading` - Uploading\n* `processing` - Processing\n* `ready` - Ready\n* `error` - Error'
        ),
    notes: zod.string().nullish(),
    error_message: zod.string().nullish(),
    video_url: zod.url().max(desktopRecordingsAppendSegmentsCreateResponseVideoUrlMax).nullish(),
    video_size_bytes: zod
        .number()
        .min(desktopRecordingsAppendSegmentsCreateResponseVideoSizeBytesMin)
        .max(desktopRecordingsAppendSegmentsCreateResponseVideoSizeBytesMax)
        .nullish(),
    participants: zod.array(zod.string()).optional().describe('List of participant names'),
    transcript_text: zod.string(),
    transcript_segments: zod
        .array(
            zod
                .object({
                    timestamp: zod.number().nullish().describe('Milliseconds from recording start'),
                    speaker: zod.string().nullish(),
                    text: zod.string(),
                    confidence: zod.number().nullish().describe('Transcription confidence score'),
                    is_final: zod.boolean().nullish().describe('Whether this is the final version'),
                })
                .describe('Serializer for individual transcript segments from AssemblyAI')
        )
        .optional()
        .describe('Transcript segments with timestamps'),
    summary: zod.string().nullish(),
    extracted_tasks: zod
        .array(
            zod
                .object({
                    title: zod.string(),
                    description: zod.string().optional(),
                    assignee: zod.string().nullish(),
                })
                .describe('Serializer for extracted tasks')
        )
        .optional()
        .describe('AI-extracted tasks from transcript'),
    tasks_generated_at: zod.iso.datetime({}).nullish(),
    summary_generated_at: zod.iso.datetime({}).nullish(),
    started_at: zod.iso.datetime({}).optional(),
    completed_at: zod.iso.datetime({}).nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})
