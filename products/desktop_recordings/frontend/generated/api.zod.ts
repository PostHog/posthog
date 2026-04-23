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
export const desktopRecordingsUpdateBodyMeetingTitleMax = 255

export const desktopRecordingsUpdateBodyMeetingUrlMax = 200

export const desktopRecordingsUpdateBodyDurationSecondsMin = -2147483648
export const desktopRecordingsUpdateBodyDurationSecondsMax = 2147483647

export const desktopRecordingsUpdateBodyVideoUrlMax = 200

export const desktopRecordingsUpdateBodyVideoSizeBytesMin = -2147483648
export const desktopRecordingsUpdateBodyVideoSizeBytesMax = 2147483647

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

/**
 * RESTful API for managing desktop meeting recordings.

Standard CRUD operations plus transcript management as a subresource.
 */
export const desktopRecordingsPartialUpdateBodyMeetingTitleMax = 255

export const desktopRecordingsPartialUpdateBodyMeetingUrlMax = 200

export const desktopRecordingsPartialUpdateBodyDurationSecondsMin = -2147483648
export const desktopRecordingsPartialUpdateBodyDurationSecondsMax = 2147483647

export const desktopRecordingsPartialUpdateBodyVideoUrlMax = 200

export const desktopRecordingsPartialUpdateBodyVideoSizeBytesMin = -2147483648
export const desktopRecordingsPartialUpdateBodyVideoSizeBytesMax = 2147483647

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
