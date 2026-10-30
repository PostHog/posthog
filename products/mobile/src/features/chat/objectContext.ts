import { OBJECT_KIND_DATA } from './objectKinds.generated'

// The item types the web's context block uses for these objects: the issue scene attaches `error_tracking_issue`
// (`ErrorTrackingIssueScene.tsx`), and the replay player attaches `session_recording` (`debugReplayPrompt.ts`). The
// agent reads the same item lines from a phone message as from a web one.
export const ISSUE_OBJECT_TYPE = 'error_tracking_issue'
export const RECORDING_OBJECT_TYPE = 'session_recording'

export type ChatObjectType = typeof ISSUE_OBJECT_TYPE | typeof RECORDING_OBJECT_TYPE

export interface ChatObjectContext {
    type: ChatObjectType
    key: string
    label: string
}

const FALLBACK_LABELS: Record<ChatObjectType, string> = {
    [ISSUE_OBJECT_TYPE]: OBJECT_KIND_DATA.error.kindLabel,
    [RECORDING_OBJECT_TYPE]: OBJECT_KIND_DATA.replay.kindLabel,
}

// Build-time strings only: they go in the trusted block, so the id and the label never enter them. The recording
// line adapts the web's replay-player instruction to a phone, which has no recording export to attach.
const OBJECT_INSTRUCTIONS: Record<ChatObjectType, string> = {
    [ISSUE_OBJECT_TYPE]:
        "The user has an error tracking issue open in the PostHog mobile app. The error_tracking_issue item's key is " +
        'the ID of that issue, and "this issue" or "this error" means that issue. Load the investigating-error-issue ' +
        'skill and fetch the issue with query-error-tracking-issue. Do not ask the user for the issue ID.',
    [RECORDING_OBJECT_TYPE]:
        "The user has a session recording open in the PostHog mobile app. The session_recording item's key is the " +
        'session ID of that recording, and "this replay" or "this recording" means that session. Load the ' +
        'investigating-replay skill and fetch the recording with session-recording-get. Do not ask the user for the ' +
        'session ID.',
}

function isObjectType(value: string | undefined): value is ChatObjectType {
    return value === ISSUE_OBJECT_TYPE || value === RECORDING_OBJECT_TYPE
}

export function objectContextFromParams(params: {
    objectType?: string
    objectId?: string
    objectLabel?: string
}): ChatObjectContext | null {
    const key = params.objectId?.trim()
    if (!isObjectType(params.objectType) || !key) {
        return null
    }
    return { type: params.objectType, key, label: params.objectLabel?.trim() || FALLBACK_LABELS[params.objectType] }
}

export function objectInstructions(object: ChatObjectContext): string {
    return OBJECT_INSTRUCTIONS[object.type]
}
