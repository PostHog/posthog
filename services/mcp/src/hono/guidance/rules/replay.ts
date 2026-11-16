import { emptyResultRule, hasArg } from '../empty-result-rule'
import type { GuidanceCall } from '../engine'
import type { GuidanceRule } from '../rule-schema'

const SESSION_RECORDINGS_LIST_TOOL = 'query-session-recordings-list'

function lookupIn(call: GuidanceCall): 'session_ids' | 'person_uuid' | 'properties' | 'none' {
    return (['session_ids', 'person_uuid', 'properties'] as const).find((name) => hasArg(call, name)) ?? 'none'
}

function replayRule(rule: {
    id: string
    recordingEnabled: boolean
    matches?: (call: GuidanceCall) => boolean
    requiresTool?: string[]
    text: string
}): GuidanceRule {
    return emptyResultRule({
        id: rule.id,
        tool: SESSION_RECORDINGS_LIST_TOOL,
        requiresTool: [SESSION_RECORDINGS_LIST_TOOL, ...(rule.requiresTool ?? [])],
        when: async ({ call, productState }) =>
            (rule.matches?.(call) ?? true) &&
            (await productState.isSessionRecordingEnabled()) === rule.recordingEnabled,
        text: rule.text,
    })
}

const rules: GuidanceRule[] = [
    replayRule({
        id: 'replay-empty-to-recording-off',
        recordingEnabled: false,
        text: [
            'Session recording is turned off for this project, so PostHog records no new sessions.',
            'Recordings made before it was turned off stay available until they expire.',
            'If the user expected recordings here, tell them that recording is off.',
            'Do not turn it on unless the user asks for that.',
        ].join(' '),
    }),
    replayRule({
        id: 'replay-empty-to-session-range',
        recordingEnabled: true,
        matches: (call) => lookupIn(call) === 'session_ids' && !hasArg(call, 'date_from'),
        text: [
            'This call passed `session_ids` without `date_from`, so it searched only the last 3 days.',
            'The date range also applies to a lookup by session ID.',
            'If the sessions can be older, call again with a `date_from` that covers them before you report that they have no recording.',
        ].join(' '),
    }),
    replayRule({
        id: 'replay-empty-to-session-missing',
        recordingEnabled: true,
        matches: (call) => lookupIn(call) === 'session_ids' && hasArg(call, 'date_from'),
        text: [
            'None of these session IDs has a recording in this date range.',
            'Not every session has a recording: sampling, recording triggers and the minimum duration can each skip a session, and recordings expire after the retention period.',
            'Check that the date range covers the time of the sessions.',
            'If it does, tell the user that these sessions were not recorded or have expired.',
        ].join(' '),
    }),
    replayRule({
        id: 'replay-empty-to-person',
        recordingEnabled: true,
        matches: (call) => lookupIn(call) === 'person_uuid',
        text: [
            'This person has no recording in this date range.',
            'Try a wider `date_from` before you report that the person has no recordings.',
            'A person can have events and no recordings, because sampling, recording triggers and the minimum duration can each skip a session.',
        ].join(' '),
    }),
    replayRule({
        id: 'replay-empty-to-filters',
        recordingEnabled: true,
        matches: (call) => lookupIn(call) === 'properties',
        requiresTool: ['read-data-schema'],
        text: [
            'Session recording is on for this project, but no recording matched the `properties` filters in this date range.',
            'Check each filter: the property name and value must exist (`read-data-schema` lists them), and `type` must match where the property is stored (`person`, `session`, `event` or `recording`).',
            'Remove or loosen the filters and try again before you report that no matching recordings exist.',
        ].join(' '),
    }),
    replayRule({
        id: 'replay-empty-to-range',
        recordingEnabled: true,
        matches: (call) => lookupIn(call) === 'none',
        requiresTool: ['docs-search'],
        text: [
            'Session recording is on for this project, but this date range has no recordings.',
            '`date_from` defaults to `-3d`. Try a wider `date_from`, and `filter_test_accounts: false` if it was set, before you report that no recordings exist.',
            'If a wide range is also empty, no recordings reach PostHog: call `docs-search` for the session replay troubleshooting steps.',
        ].join(' '),
    }),
]

export default rules
